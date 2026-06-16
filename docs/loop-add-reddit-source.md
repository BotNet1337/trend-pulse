# Runbook — добавить Reddit как третий источник через `/loop`

Автономный прогон: **спланировать** (`/next:trendpulse-plan`) и **реализовать** (`/next:trendpulse-executor`)
Reddit-источник виральности в TrendPulse — точной калькой с Twitter-источника
([ADR-001 source-abstraction](./architecture/adr-001-source-abstraction.md), эталон —
[TASK-031](./tasks/task-031-twitter-source.md) + [twitter-data-guide](./twitter-data-guide.md)).

Прогон — **в две стадии**:
- **ФАЗА 1 (автономно, без вопросов):** код+тесты+доки до merge трёх PR. Завершается на owner-gate.
- **ФАЗА 2 (после того как владелец добавит ключ):** **live-валидация на проде** — `make deploy` +
  доказательство, что Reddit-посты реально текут через pipeline и получают `viral_score` (как у Twitter).

После ФАЗЫ 1 владельцу останется **только выпустить Reddit-ключ и положить его в env/vault**; затем он
переснимает луп — и ФАЗА 2 проверяет прод.

## Как запускать

1. Запускай Claude Code **из** `apps/trendPulse` (там активны trendpulse-скиллы и хуки).
2. Предусловие для PR: git-репозиторий + remote + `gh auth login` заранее. Луп забутстрапит репозиторий, но
   при отсутствии remote — **один** раз спросит про `gh repo create` (это инфраструктурный пререквизит, не
   продуктовый вопрос).
3. Введи `/loop` **без интервала** (self-paced) и вставь промпт ниже. Прогон сам спланирует задачи
   TASK-092..094, затем по одной их реализует (PR → green CI → squash-merge → следующая), скидывая память
   между задачами. Когда все три `done` — луп **встаёт на owner-gate** (ФАЗА 2) и ждёт ключ, НЕ завершаясь
   полностью: выводит, что нужно от владельца.
4. **Владелец:** выпускает Reddit-ключ по `docs/reddit-data-guide.md`, кладёт `REDDIT_CLIENT_ID`/
   `REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT` в env (дев) / Ansible vault (прод), и пишет в лупе «ключ добавлен»
   (или переснимает `/loop` с тем же промптом). Тогда запускается **ФАЗА 2 — live-валидация на проде**.

```
/loop
```

## Промпт (вставить после /loop)

> Ты — оркестратор автономного добавления **Reddit как третьего источника** в TrendPulse. Рабочая
> директория: `/Users/macbookpro16/work/botnet/apps/trendPulse`. Общайся по-русски. Соблюдай
> `docs/CONVENTIONS.md` и архитектуру в `docs/architecture/` (особенно
> [ADR-001 source-abstraction](./architecture/adr-001-source-abstraction.md)). Источник истины о прогрессе —
> frontmatter `status` + блок `Checkpoints` (`current_step`) в `docs/tasks/task-09{2,3,4}-*.md` и
> `docs/tasks/tasks-index.md`. **Режим — автоматический, без вопросов ко мне**, кроме (а) инфраструктурного
> bootstrap remote и (б) настоящих внешних блокеров (нужен новый секрет/решение, не выводимое из кода/доков).
>
> **ЭТАЛОН (копировать, не изобретать):** Twitter-источник — [ADR-001](./architecture/adr-001-source-abstraction.md),
> [TASK-031](./tasks/task-031-twitter-source.md) (collector core), [TASK-089](./tasks/task-089-twitter-seed-pack.md)
> (seed-pack), [TASK-090](./tasks/task-090-twitter-data-instructions.md) +
> [twitter-data-guide.md](./twitter-data-guide.md) (owner-инструкция). Код-эталон:
> `backend/src/collector/twitter/{client,reader,mapper,dedup}.py`, регистрация в
> `backend/src/collector/registry.py` (`_build_twitter_collector` + `register(SourceKind.TWITTER, …)`),
> settings в `backend/src/config.py`, константы в `backend/src/collector/constants.py`, тесты
> `backend/tests/unit/collector/test_twitter_collector.py`. **Ядро (`collector/base.py`, pipeline, scorer, API)
> НЕ трогать** — оно платформо-независимо по ADR-001; добавление источника = новая реализация `SourceCollector`
> Protocol + регистрация.
>
> **ФАЗА 0 — ПЛАНИРОВАНИЕ (один раз, если задач ещё нет).** Если `docs/tasks/task-092-*.md` не существует —
> запусти **`/next:trendpulse-plan`** и создай ровно три task-дока (зеркало Twitter-декомпозиции),
> каждый со стандартным контрактом (frontmatter, Discussion, Scope «Touch ONLY / Do NOT touch / Blast radius»,
> Given/When/Then AC, Plan, Invariants, Edge cases, Test plan, Checkpoints `current_step: 3`, стадии 1–2 ✓),
> зафиксируй `baseline_commit` и обнови `tasks-index.md`. Decisions ниже уже приняты — внеси их в `## Discussion`
> как defaults, **ничего не спрашивай**:
>
> - **TASK-092 — Reddit source core** (зеркало TASK-031). Scope: `backend/src/collector/reddit/`
>   (`__init__.py`, `client.py` — OAuth2 application-only клиент + token-refresh, `reader.py` —
>   `RedditCollector(SourceCollector)` с `kind=SourceKind.REDDIT`/`validate_ref`/`read`, `mapper.py` —
>   submission→`RawPost`/`PostMetrics`, `dedup.py`); `collector/registry.py` (`_build_reddit_collector` +
>   `register(SourceKind.REDDIT, …)`); `collector/base.py::SourceKind` — добавить `REDDIT = "reddit"` (это
>   единственное допустимое изменение в base.py — расширение enum, контракт не меняется; проверить тип столбца
>   `Channel.source_kind` — он `native_enum=False` VARCHAR, миграция НЕ нужна, как у Twitter);
>   `backend/src/config.py` (`reddit_client_id`/`reddit_client_secret`/`reddit_user_agent`/`reddit_api_base_url`
>   — optional, None-guard); `collector/constants.py` (Reddit-константы, см. §Reddit-spec); per-source
>   `REDDIT_HANDLE_PATTERN` + валидация по `source_kind` в `api/watchlist/schemas.py`; `.env.example` +
>   `release/deployment.example/sensitive.env.example`. Тесты: `test_reddit_collector.py` (Protocol-isinstance,
>   маппинг метрик на замоканном API — respx/fake, `posted_at` UTC, `external_id` dedup) + integration
>   watchlist `source_kind=reddit` на моке. Celery-таск НЕ нужен (`collect_watched_sources` уже source-agnostic).
> - **TASK-093 — Reddit seed-pack** (зеркало TASK-089): pack «Crypto Reddit (RU+EN)» через packs-фичу
>   (`PackChannel(kind=SourceKind.REDDIT)`) в `backend/src/api/packs/data.py`; кандидаты-сабреддиты
>   валидируются `validate_ref` (owner-gated live — нужен ключ; до ключа мёртвые молча пропускаются).
> - **TASK-094 — Reddit owner-инструкция** (зеркало TASK-090): `docs/reddit-data-guide.md` (рус) — какой доступ
>   оформить (Reddit app «script»/app-only OAuth2, бесплатно), как выпустить client_id/secret, env-имена,
>   эндпоинты/поля, лимиты, как добавлять сабреддиты, что произойдёт после установки ключа.
>
> После создания трёх доков — сообщи кратко и переходи к ФАЗЕ 1.
>
> **ФАЗА 1 — РЕАЛИЗАЦИЯ (итерация, ровно одна задача за ход).** Идемпотентно: каждую итерацию заново читай
> статусы с диска и продолжай. Порядок по зависимостям: **092 → 093 → 094** (093 и 094 зависят от 092).
> 1. **Выбор.** Возьми task с наименьшим номером, у которого `status != done` И все deps `done`.
>    Если все три `done` → ЗАВЕРШЕНИЕ.
> 2. **Статус.** В доке: `status: in-progress`, `updated:` = сегодня, `lock` = id рана. Сохрани.
> 3. **Выполнение.** Запусти **`/next:trendpulse-executor`** для этой TASK-NNN. Он войдёт на `current_step` и
>    проведёт `do (TDD RED→GREEN) → verify (G2) → review ∥ security → ship`, тикая Checkpoints. Reddit API —
>    **внешняя зависимость**: тесты гоняются против ЗАМОКАННОГО API (respx/fake), CI реальный Reddit не дёргает.
> 4. **Валидация перед ship.** Все AC выполнены с доказательствами; Checkpoints 1–5 (+5.5 если применимо) ✓;
>    diff строго в Scope; `make ci-fast` зелёный (ruff+mypy+pytest); ядро (`base.py` кроме +1 enum, pipeline,
>    scorer) не в диффе.
> 5. **Ship → merge (АВТОНОМНО, без вопросов).** Ветка `gsd/phase-{NNN}-reddit-*`, Conventional Commit
>    (код+доки в одном PR), `git push -u`, `gh pr create`. Когда CI зелёный — `gh pr merge --squash
>    --delete-branch` **сам** (мердж в `main` напрямую запрещён хуком — только через PR). Затем `status: done`,
>    тикни Checkpoints 6+7, `current_step: done`, очисти `lock`, обнови `tasks-index.md`, выполни стадию
>    learnings (допиши `docs/learnings.md`).
> 6. **СКИНЬ ПАМЯТЬ (обязательно, для экономии контекста).** После merge каждой задачи запиши краткий итог в
>    `/Users/macbookpro16/.claude/projects/-Users-macbookpro16-work-botnet/memory/` (одна задача = строка-итог:
>    TASK · PR · что сделано · остаток) и обнови `MEMORY.md`-индекс. Это разгружает контекст между задачами.
> 7. **Дальше.** Краткий итог, переход к следующей итерации.
>
> **ПРАВИЛА:** одна задача за ход; уважай deps (092 первой); только PR-flow; всё через `make` (не raw
> `docker compose`/`pytest`); ядро не трогать (кроме +1 значения в `SourceKind` enum); без вопросов ко мне,
> кроме bootstrap-remote и настоящего внешнего блокера (новый секрет/продуктовое решение, не выводимое из
> кода+доков) → тогда HALT с конкретным вопросом, не угадывай.
>
> **КОНЕЦ ФАЗЫ 1 → OWNER-GATE:** когда TASK-092/093/094 все `status: done` — выведи сводку (таблица: задача ·
> PR · итог), скинь память, и **встань на owner-gate**: явно напиши, что владельцу нужно (1) выпустить
> Reddit-ключ по `docs/reddit-data-guide.md`, (2) положить `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/
> `REDDIT_USER_AGENT` в env (дев) / Ansible vault (прод), (3) сообщить «ключ добавлен». **Не завершай луп
> полностью и не угадывай, что ключ уже есть** — заверши ход и жди (без wakeup только ради ожидания).
>
> **ФАЗА 2 — LIVE-ВАЛИДАЦИЯ НА ПРОДЕ (запускается, когда владелец сказал «ключ добавлен»).** Это **поведенческое
> доказательство (G2)**, что Reddit реально работает в проде, а не только в моках CI. Трекинг — секция
> `## Reddit live-verify` в `docs/api-e2e-status.md` (создай, если нет). Шаги (всё через `make`, не raw
> docker/curl-в-обход-nginx):
> 1. **Деплой ключа.** `make ansible-unpack` (материализует env из vault) → `make deploy` (provision→TLS→stack).
>    Убедись, что `REDDIT_*` доехали в контейнер воркера (env присутствует, в логах **маскирован**, не в открытом
>    виде).
> 2. **Коллектор поднялся.** В логах воркера (`make logs`) после рестарта: `registry.get(REDDIT)` строит
>    `RedditCollector` (НЕ warn-once «unconfigured» no-op). OAuth2-токен получен (`access_token` есть, без утечки).
> 3. **Ингест идёт.** Подпишись на pack «Crypto Reddit» (TASK-093) у тест-пользователя → дождись 1–2 тиков
>    (`REDDIT_COLLECT_INTERVAL_SECONDS`=300) → в логах видно чтение `/r/{sub}/new`, посты пишутся в буфер;
>    `external_id` (`t3_…`) уникальны, `posted_at` tz-aware UTC, `score→reactions`/`num_crossposts→forwards`.
> 4. **Pipeline + score.** Reddit-посты прошли dedup→normalize→embed→cluster→score: в БД/витринах появляются
>    кластеры с `source_kind=reddit` (или смешанные TG+Twitter+Reddit) и **`viral_score > 0`** хотя бы у части.
>    Это и есть главный критерий — Reddit-сигнал виден наравне с TG/Twitter.
> 5. **Здоровье стека не деградировало.** Все сервисы up (как при предыдущих deploy — 11/11), Redis без OOM,
>    rate-limit Reddit уважается (нет 429-шторма в логах), TG/Twitter-ингест не сломан.
> 6. **Owner-gated тупики → HALT, не угадывай:** ключ невалиден/403, сабреддиты приватные/мёртвые, прод
>    недоступен → останови, напиши конкретно, что не так и что нужно от владельца.
>
> **ЗАВЕРШЕНИЕ (после ФАЗЫ 2):** запиши результаты live-verify в `docs/api-e2e-status.md` + `docs/learnings.md`,
> скинь финальную память, выведи вердикт (Reddit-ингест **доказанно** работает на проде: ссылка на логи/кластеры
> со `viral_score>0`, либо честный список того, что owner-blocked) и **заверши луп** (не планируй wakeup).

## Reddit-spec (defaults для плана — выводимы из Reddit API, спрашивать нечего)

- **Доступ:** Reddit OAuth2, **application-only** (тип app «script»/«web»), read-only публичные данные —
  **бесплатно** (в отличие от Twitter pay-per-use). Токен: `POST https://www.reddit.com/api/v1/access_token`
  (`grant_type=client_credentials`, Basic-auth client_id:client_secret), API после auth —
  `https://oauth.reddit.com`. Reddit **требует уникальный `User-Agent`**.
- **Env-имена:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`
  (+ optional `REDDIT_API_BASE_URL`). Пусто = Reddit-ингест выключен (warn-once no-op, как пустой TG-пул /
  пустой Twitter-Bearer). В коде — `config.Settings` optional None-guard, маскировать в логах.
- **handle = сабреддит** без префикса `r/`, 3–21 символ `[A-Za-z0-9_]` → `REDDIT_HANDLE_PATTERN`.
- **Эндпоинты:** `GET /r/{sub}/about` (validate_ref — сабреддит существует/публичный),
  `GET /r/{sub}/new?limit=N` (свежие посты; пагинация `before`/фильтр по `created_utc >= since`).
- **Маппинг метрик** (submission → `PostMetrics`, всегда int, не None):
  `score`(ups) → `reactions`, `num_crossposts` → `forwards`, `views` → **0** (Reddit не отдаёт просмотры в API);
  `num_comments` / `upvote_ratio`×100 / `total_awards_received` → `extra`. `external_id` = id поста (`t3_…`),
  `posted_at` = `created_utc` (epoch) → tz-aware UTC.
- **Кадэнс/лимиты** (named-константы в `collector/constants.py`): `REDDIT_COLLECT_INTERVAL_SECONDS = 300`
  (5 мин — Reddit дешевле Twitter, но не спамим), `REDDIT_MAX_RESULTS_PER_TICK = 50`. Rate-limit: free OAuth
  ~100 QPM; уважать `X-Ratelimit-Remaining`/`X-Ratelimit-Reset` и 429-backoff внутри collector (как
  Twitter 429-cap / TG FLOOD_WAIT). Жёсткий месячный read-budget НЕ нужен (нет per-read цены) — достаточно
  rate-limit-aware backoff; зафиксировать это как осознанное решение.
- **Лимиты планов:** оставить **суммарный** `Resource.CHANNELS` (как решено для Twitter в ADR-001 §schema) —
  минимальный путь, без per-source разбивки.

## Что произойдёт после установки ключа (owner) — это и проверяет ФАЗА 2

1. Владелец выпускает Reddit app + кладёт `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT` в
   env (дев) / Ansible vault (прод) → `make deploy`.
2. Перезапуск воркера → `registry.get(REDDIT)` строит collector (ключ есть).
3. Source-agnostic `collect_tick` начинает читать REDDIT-рефы из watchlist'ов/паков.
4. Reddit-посты проходят тот же pipeline (dedup→normalize→embed→cluster→score) → `viral_score` наравне с
   TG/Twitter; кросс-источниковая кластеризация объединяет одну тему из TG, Twitter и Reddit.
