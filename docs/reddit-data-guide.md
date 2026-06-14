# Reddit — инструкция по данным (для владельца)

> Как подключить Reddit как источник виральности в TrendPulse: какой доступ оформить, как
> выпустить ключ, под какими именами положить в окружение, какие данные мы берём, лимиты,
> как добавлять сабреддиты. Связано: [TASK-092](./tasks/task-092-reddit-source.md),
> [TASK-093](./tasks/task-093-reddit-seed-pack.md), runbook [loop-add-reddit-source](./loop-add-reddit-source.md).
> Аналог для Twitter: [twitter-data-guide](./twitter-data-guide.md).

## 1. Какой доступ оформить (тариф)

Reddit **API (OAuth2)**, тип доступа — **application-only** (без логина пользователя), чтение
публичных данных.

- **Бесплатно** для read-only публичного контента в рамках free-rate-limit (в отличие от Twitter/X,
  где каждое чтение платное). **Нет per-read цены → в коде НЕТ месячного read-budget** — только
  rate-limit-aware backoff.
- Rate-limit free OAuth: **~100 запросов/мин** (заголовки `X-Ratelimit-Remaining`/`X-Ratelimit-Reset`).
- Reddit **требует уникальный `User-Agent`** на каждый запрос (без него — 429/403).

> Мы только ЧИТАЕМ публичные посты сабреддитов → app-only OAuth2 (`client_credentials`). Платить не
> нужно; достаточно держать кадэнс спокойным и уважать 429.

## 2. Как выпустить ключ (client_id + secret)

1. Залогиниться на Reddit под аккаунтом, от имени которого регистрируешь приложение.
2. Открыть <https://www.reddit.com/prefs/apps> → **«create another app…»** (внизу).
3. Заполнить:
   - **name**: например `trendpulse`;
   - **тип**: выбрать **«script»** (или «web app») — нам нужен application-only read;
   - **redirect uri**: можно любой валидный (например `http://localhost:8080`) — для
     `client_credentials` он не используется;
   - **description**: произвольно.
4. После создания:
   - **client_id** — короткая строка под названием приложения (прямо под «personal use script»);
   - **secret** — поле **«secret»**.
5. Придумать **User-Agent** в формате, который Reddit рекомендует:
   `platform:appname:version (by /u/username)` — например
   `trendpulse:v1.0 (by /u/yourusername)`.

## 3. Куда положить ключ (env-переменные)

Три переменные:

| Переменная | Что | 
|---|---|
| `REDDIT_CLIENT_ID` | client_id приложения |
| `REDDIT_CLIENT_SECRET` | secret приложения |
| `REDDIT_USER_AGENT` | уникальный User-Agent (см. §2.5) |

(опционально: `REDDIT_API_BASE_URL` / `REDDIT_OAUTH_BASE_URL` — хосты API/токена; по умолчанию
`https://oauth.reddit.com` и `https://www.reddit.com`, менять не нужно.)

- **Локально/дев:** в `*.env` (см. `release/deployment.example/sensitive.env.example`, строки
  `REDDIT_CLIENT_ID=`/`REDDIT_CLIENT_SECRET=`/`REDDIT_USER_AGENT=`). Все три пустые = Reddit-ингест
  выключен (коллектор не строится, тик по REDDIT-рефам — warn-once no-op, как пустой Telegram-пул /
  пустой Twitter-Bearer).
- **Прод (Ansible vault):** добавить `vault_reddit_client_id` / `vault_reddit_client_secret` /
  `vault_reddit_user_agent` в зашифрованный `ops/ansible/vault/sensitive.vault.yml` (как
  `vault_twitter_bearer_token` / `vault_telegram_*`), пробросить в `group_vars` → контейнер получает
  env `REDDIT_*` → `make deploy`.
  Никогда не коммить ключ в открытом виде / не клади в логи (он маскируется в коде).

В коде читаются из `config.Settings.reddit_client_id/reddit_client_secret/reddit_user_agent`
(optional, None-guard).

## 4. Что именно мы читаем (OAuth2, эндпоинты, поля, лимиты)

**OAuth2 (application-only):**
- `POST https://www.reddit.com/api/v1/access_token` (`grant_type=client_credentials`, HTTP Basic-auth
  `client_id:client_secret`, заголовок `User-Agent`) → короткоживущий `access_token` (~1ч). Коллектор
  кэширует токен и рефрешит по истечении (и однократно при 401). API после auth — на
  `https://oauth.reddit.com`.

**Эндпоинты:**
- `GET /r/{subreddit}/about` — проверка, что сабреддит существует/публичен (`validate_ref`).
- `GET /r/{subreddit}/new?limit=N` — свежие посты сабреддита (фильтр по `created_utc >= since`).

**Маппинг метрик** (submission → наш `PostMetrics`, всегда int, не None):
`score` (upvotes) → `reactions`, `num_crossposts` → `forwards`, `views` → **0** (Reddit не отдаёт
просмотры в API); `num_comments` / `upvote_ratio`×100 / `total_awards_received` → `extra`.
`external_id` = fullname поста (`t3_…`), `posted_at` = `created_utc` (epoch) → tz-aware UTC.

**Лимиты (named-константы в `backend/src/collector/constants.py`):**
- `REDDIT_COLLECT_INTERVAL_SECONDS = 300` — Reddit опрашивается **раз в 5 мин** (дешевле Twitter, но
  не спамим).
- `REDDIT_MAX_RESULTS_PER_TICK = 50` — не более 50 постов с сабреддита за тик.
- `REDDIT_RATE_LIMIT_INLINE_CAP_SECONDS = 60` — 429: короткий reset → коллектор ждёт и повторяет;
  длинный → пропускает сабреддит до следующего тика (никогда не вешает тик).
- **Месячного read-budget НЕТ** (нет per-read цены) — только rate-limit-aware backoff.

## 5. Как добавить сабреддиты (pack)

Сабреддиты живут в pack-каталоге наравне с TG-каналами и Twitter-аккаунтами:
`backend/src/api/packs/data.py` → pack `crypto-reddit` → список
`PackChannel("subreddit", kind=SourceKind.REDDIT)`.

- handle — **имя сабреддита без `r/`, строчными**, 3–21 символ `[a-z0-9_]` (правило имён сабреддитов;
  дефисы недопустимы).
- Добавление/удаление — правкой `data.py` + PR (как у TG/Twitter-паков, без admin-UI).
- Дефолтный seed-pack «Crypto Reddit (RU+EN)» уже собран (кандидаты). После того как ключ появится,
  прогон через `validate_ref` отсеет мёртвые/приватные (TASK-093); до ключа мёртвые просто молча
  пропускаются коллектором при чтении.

## 6. Что произойдёт после установки ключа

1. Положить `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT` в env (дев) / vault (прод) →
   `make deploy`.
2. Перезапуск воркера → `registry.get(REDDIT)` строит коллектор (ключ есть; OAuth2-токен получен).
3. Тик `collect_tick` (source-agnostic) начнёт читать REDDIT-рефы из watchlist'ов/паков.
4. Reddit-посты пройдут тот же pipeline (dedup→normalize→embed→cluster→score) → получат
   `viral_score` наравне с TG/Twitter; кросс-источниковая кластеризация объединит одну тему из TG,
   Twitter и Reddit.
5. Проверка (owner/loop, **ФАЗА 2 live-verify**): подписаться на pack `crypto-reddit`, дождаться 1–2
   тиков (5 мин), увидеть в логах чтение `/r/{sub}/new` и в витринах — кластеры с `source_kind=reddit`
   и `viral_score > 0`.

## Чек-лист владельца (что сделать)

- [ ] Создать Reddit app («script») на <https://www.reddit.com/prefs/apps>, взять `client_id` + `secret`.
- [ ] Придумать уникальный `User-Agent`.
- [ ] Положить `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` в env (дев) или
      Ansible vault (прод, `vault_reddit_*`), затем `make deploy`.
- [ ] Сообщить в loop «ключ добавлен» → запустится **ФАЗА 2** (live-валидация на проде).
