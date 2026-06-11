# ADR-008 — At-rest field encryption: Fernet TypeDecorator + lazy key + migration strategy

**Status:** Accepted  
**Date:** 2026-06-11  
**Task:** [TASK-032](../tasks/task-032-security-hardening.md) — Security hardening (closes P5)  
**Supersedes:** P5 accepted-risk (pain-points.md, 2026-06-09)

---

## Context

`users.telegram_bot_token` и `users.webhook_url` хранились в Postgres в открытом виде (P5 pain-points).
Компенсирующие меры (TLS in-transit, изолированная сеть `postgres_net`, scrub в Sentry/логах)
снижали риск, но не устраняли его. Перед публичным запуском / первым B2B-клиентом решено
реализовать at-rest шифрование на app-уровне.

Три альтернативы рассматривались:

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| **pgcrypto** (pg extension) | Прозрачно для приложения; key никогда не покидает DB layer | Требует расширения (не всегда доступно на managed); ключ в БД же; сложнее ротация |
| **App-level Fernet** (выбрано) | Без расширений; ключ в env/vault (app layer); переносимо; тестируется без PG | Overhead на каждый read/write; потеря ключа = потеря данных |
| **Accepted risk** | Нулевые изменения | Неприемлемо перед публичным запуском |

Выбор: **App-level Fernet** (`cryptography` library) через SQLAlchemy `TypeDecorator`.

---

## Decision

### 1. TypeDecorator `EncryptedString`

`backend/src/storage/encryption.py` — `EncryptedString(TypeDecorator[str])`:

- `impl = String` — underlying column остаётся VARCHAR (увеличен до 300/2300 char соответственно).
- `process_bind_param`: encrypt plaintext → Fernet token (urlsafe-base64 str) на write.
- `process_result_value`: decrypt Fernet token → plaintext str на read. `InvalidToken` → fallback return as-is с WARNING (dual-read при rolling deploy).
- `None` значения проходят без изменений (nullable columns).
- `cache_ok = True`: нет per-instance state, влияющего на кеш SQL.

Использование в `storage/models/users.py`:

```python
telegram_bot_token: Mapped[str | None] = mapped_column(EncryptedString(300), nullable=True)
webhook_url: Mapped[str | None] = mapped_column(EncryptedString(2300), nullable=True)
```

### 2. Lazy key resolution

**Проблема:** `configure(key)` classmethod, вызываемый в `api/main.py` при старте API, не виден
Celery worker'у — worker грузится через `celery_app.py`, не импортирует `api.main`.
Класс-переменная `_encryption_key` оставалась `""` в worker → `RuntimeError` при первом ORM-чтении.

**Решение:** TypeDecorator резолвит ключ ЛЕНИВО из `get_settings()` (lru_cached) внутри
`process_bind_param`/`process_result_value`. После первого вызова это дешёвый dict lookup.
`configure()` classmethod и `_encryption_key` class-var удалены.

```python
def _get_encryption_key() -> str:
    from config import get_settings
    return get_settings().field_encryption_key
```

**Правило:** любой ресурс, нужный и API и Celery worker, резолви лениво из settings,
не через app-startup-инициализацию.

### 3. Key management

- Переменная: `FIELD_ENCRYPTION_KEY` (env / Ansible vault → `sensitive.env.j2`).
- Формат: Fernet key = 32-byte urlsafe-base64 (генерируется `Fernet.generate_key()`).
- Валидация при старте: `field_validator("field_encryption_key")` в `config.py` — fail fast
  если не base64url или не 32 байт после decode.
- Dev default: `_make_dev_fernet_key()` (детерминированный placeholder, не хранится нигде —
  только для `uv run pytest` без env). НЕ использовать на prod.
- Потеря ключа: постоянная потеря зашифрованных данных колонок. Хранить в secret manager
  с backup. Ротация: decrypt all → re-encrypt with new key → deploy.

### 4. Migration strategy (migration 0019)

`backend/migrations/versions/0019_field_encryption.py`:

- `upgrade()`: расширяет колонки (VARCHAR 300/2300); шифрует существующие plaintext-строки.
  Идемпотентность: строки, начинающиеся с `gAA` (Fernet prefix), пропускаются.
- `downgrade()`: decrypt all encrypted values → plaintext; сужает колонки обратно.
- **Rolling deploy:** `InvalidToken` fallback в `process_result_value` позволяет читать
  plaintext-строки (pre-migration rows) без краша. Это dual-read окно — убирается после
  полного прогона миграции на всех узлах.

### 5. Decrypt-at-use

TypeDecorator автоматически расшифровывает при ORM-чтении → `user.telegram_bot_token` всегда
возвращает plaintext. Call-site'ы (notifier, webhook delivery, `delivery_config` PATCH, mask_bot_token)
изменений не требуют — они уже читают ORM-атрибут.

Маскирование в API (`mask_bot_token`, TASK-017) не конфликтует: маска применяется к уже
расшифрованному plaintext значению.

---

## Consequences

**Позитивные:**
- P5 закрыт: утечка дампа БД не раскрывает токены без ключа.
- Прозрачно для всего кода, читающего ORM — нет изменений в delivery/notifier путях.
- Работает и в API процессе и в Celery worker без взаимной зависимости на app-startup.

**Риски / ограничения:**
- Потеря `FIELD_ENCRYPTION_KEY` = потеря доступа к токенам пользователей. Vault backup обязателен.
- Небольшой overhead (~1ms) на каждый encrypt/decrypt (Fernet HMAC-SHA256 + AES-CBC). Приемлемо
  для write-редких колонок.
- При ротации ключа: downtime или online migration (decrypt old / re-encrypt new).
- Dev default не защищает данные dev-БД (это ожидаемое поведение для dev).

**Перед prod deploy:**
- Сгенерировать ключ: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- Положить в Ansible vault: `vault_field_encryption_key`.
- Прогнать migration 0019 на prod БД ДО деплоя нового образа.
- После деплоя: убедиться что `FIELD_ENCRYPTION_KEY` в env контейнеров и worker виден одинаковый ключ.

---

## Related

- [ADR-005](./adr-005-infra-provisioning-and-secrets.md) — secrets management (Ansible vault)
- [pain-points.md P5](./pain-points.md#p5--закрыт-task-032-2026-06-11)
- [TASK-032](../tasks/task-032-security-hardening.md) — полный контекст, debug-записи
