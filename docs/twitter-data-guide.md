# Twitter/X — инструкция по данным (для владельца)

> Как подключить Twitter/X как источник виральности в TrendPulse: какой доступ оформить, как
> выпустить ключ, под каким именем положить в окружение, какие данные мы берём, лимиты и расходы,
> как добавлять аккаунты. Связано: [research-бриф](./research/twitter-source-research-brief.md),
> [TASK-031](./tasks/task-031-twitter-source.md), [TASK-089](./tasks/task-089-twitter-seed-pack.md).

## 1. Какой доступ оформить (тариф)

X (Twitter) API **v2**. С февраля 2026 старые фикс-тарифы **Basic ($200/мес) и Pro ($5000/мес)
закрыты для новых аккаунтов** — новым разработчикам выдаётся **pay-per-use**:

- **$0.005 за чтение одного поста**, $0.01 за публикацию;
- **кап 2 000 000 чтений/мес**;
- rate-limit: 15-минутные скользящие окна (отдельно per-app по Bearer и per-user по OAuth).

> Мы только ЧИТАЕМ публичные твиты → нужен app-only доступ (Bearer). Платим за чтения. Поэтому в
> коде есть жёсткий **месячный лимит чтений** (см. §4) — защита от неконтролируемого расхода.

Если у тебя уже есть legacy Basic — он тоже подойдёт (тот же v2, те же эндпоинты).

## 2. Как выпустить ключ (Bearer Token)

1. Завести developer-аккаунт: <https://developer.x.com> → Sign up / Apply.
2. Создать **Project** и внутри него **App**.
3. В приложении: **Keys and tokens** → раздел **Bearer Token** → **Generate** → скопировать.
   (Нам нужен ТОЛЬКО Bearer Token — это app-only read-credential. API Key/Secret и Access
   Token/Secret для нашего сценария чтения не требуются.)

## 3. Куда положить ключ (env-переменная)

Имя переменной — **`TWITTER_BEARER_TOKEN`**.

- **Локально/дев:** в `*.env` (см. `release/deployment.example/sensitive.env.example`, строка
  `TWITTER_BEARER_TOKEN=`). Пустое значение = Twitter-ингест выключен (коллектор не зарегистрируется
  как активный, тик по TWITTER-рефам — warn-once no-op, как пустой Telegram-пул).
- **Прод (Ansible vault):** добавить `vault_twitter_bearer_token` в зашифрованный
  `ops/ansible/vault/sensitive.vault.yml` (как `vault_telegram_*`), пробросить в `group_vars` →
  контейнер получает env `TWITTER_BEARER_TOKEN` → `make deploy`.
  Никогда не коммить ключ в открытом виде / не клади в логи (он маскируется в коде).

В коде ключ читается из `config.Settings.twitter_bearer_token` (optional, None-guard).

## 4. Что именно мы читаем (эндпоинты, поля, лимиты)

**Эндпоинты v2:**
- `GET /2/users/by/username/{username}` — резолв @handle → user id (и проверка существования,
  `validate_ref`).
- `GET /2/users/{id}/tweets` — недавние твиты аккаунта; параметры:
  `start_time` (нижняя граница = время прошлого тика), `max_results`,
  `tweet.fields=public_metrics,created_at`.

**Маппинг метрик** (`public_metrics` → наш `PostMetrics`):
`like_count → reactions`, `retweet_count → forwards`, `impression_count → views` (если недоступен на
тарифе — 0); `reply_count`/`quote_count`/`bookmark_count` → `extra`.

**Лимиты и расходы (named-константы в `backend/src/collector/constants.py`):**
- `TWITTER_COLLECT_INTERVAL_SECONDS = 900` — Twitter опрашивается **раз в 15 мин** (не 60с как TG),
  чтобы экономить чтения.
- `TWITTER_MAX_RESULTS_PER_TICK = 25` — не более 25 твитов с аккаунта за тик.
- `MAX_TWITTER_READS_PER_MONTH = 100_000` — жёсткий месячный кап. При достижении коллектор
  останавливает чтение Twitter и шлёт ops-алерт **один раз за месяц** (счётчик в Redis,
  `twitter:reads:{YYYY-MM}`). Подними/опусти значение под свой бюджет.
- 429 (rate-limit): короткий reset → коллектор ждёт и повторяет; длинный → пропускает аккаунт до
  следующего тика (никогда не вешает тик).

**Грубая оценка расхода:** ~30 аккаунтов × ~10 новых твитов × 96 тиков/день ≈ 28 800 чтений/день ≈
**~860k/мес ≈ ~$4 300/мес** при максимальной активности. Поэтому: держи список аккаунтов
компактным, кадэнс редким, и используй `MAX_TWITTER_READS_PER_MONTH` как потолок. Для пилота
поставь кап заметно ниже (например 50–100k чтений/мес).

## 5. Как добавить аккаунты (pack)

Twitter-аккаунты живут в pack-каталоге наравне с TG-каналами:
`backend/src/api/packs/data.py` → pack `crypto-twitter` → список `PackChannel("username",
kind=SourceKind.TWITTER)`.

- handle — **bare username без '@', строчными**, ≤15 символов (правило X).
- Добавление/удаление — правкой `data.py` + PR (как у TG-паков, без admin-UI).
- Дефолтный seed-pack «Crypto Twitter (RU+EN)» уже собран (кандидаты). После того как ключ
  появится, прогон через `validate_ref` отсеет мёртвые/переименованные (TASK-089); до ключа
  мёртвые просто молча пропускаются коллектором при чтении.

## 6. Что произойдёт после установки ключа

1. Перезапуск воркера → `registry.get(TWITTER)` строит коллектор (ключ есть).
2. Тик `collect_tick` (source-agnostic) начнёт читать TWITTER-рефы из watchlist'ов/паков.
3. Twitter-посты пройдут тот же pipeline (dedup→normalize→embed→cluster→score) → получат
   `viral_score` наравне с TG; кросс-источниковая кластеризация объединит одну тему из TG и Twitter.
4. Проверка (owner/loop): подписаться на pack `crypto-twitter`, увидеть твиты со скором.
