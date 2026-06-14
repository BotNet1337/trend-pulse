# Research-бриф: Twitter/X как второй источник виральности (ФАЗА B)

- Дата: 2026-06-14 · Автор: twitter-source loop (итерация 3, ФАЗА B)
- Контекст: [ADR-001 source-abstraction](../architecture/adr-001-source-abstraction.md),
  [TASK-031](../tasks/task-031-twitter-source.md), память `trendpulse-product-strategy`
  (кросс-канальная виральность + independence/collusion-граф = моат).
- Цель брифа: зафиксировать подход, дефолты и нарезку задач C1–C7 ПЕРЕД кодом. Дефолты приняты
  автономно (automode) и зафиксированы здесь + в task-doc'ах.

---

## 1. Ключевое ограничение: экономика X API (2026)

**Главный вывод, переворачивающий дизайн:** в отличие от Telegram (бесплатный MTProto-пул),
X/Twitter API — платный и с февраля 2026 **старые фикс-тарифы Basic ($200/мес) и Pro ($5000/мес)
ЗАКРЫТЫ для новых аккаунтов**. Новым разработчикам выдаётся **pay-per-use**:
- **$0.005 за чтение одного поста**, $0.01 за публикацию; **кап 2 млн чтений/мес** (≈ $10k потолок).
- Rate-limit: 15-мин скользящие окна, отдельно per-app (Bearer) и per-user (OAuth).

Источники: [xpoz.ai](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/),
[twitterapi.io](https://twitterapi.io/blog/x-api-cost-breakdown-2026), [getxapi](https://www.getxapi.com/twitter-api-pricing).

**Следствия для дизайна (ОБЯЗАТЕЛЬНЫЕ):**
1. **Read-budget — центральная величина.** Наивный поллинг 25 аккаунтов × ~10 твитов × каждые 60с
   (как TG) = сотни тысяч чтений/день → тысячи $/мес. Недопустимо.
2. **Дефолт-кадэнс Twitter РЕДКИЙ:** опрос раз в **15 мин** (не 60с), `max_results` маленький,
   только `since_id`/`start_time` с прошлого тика. → ~25 акк × 96 тиков/день × ≤10 твитов ≈ 24k
   чтений/день ≈ 720k/мес. Всё равно много → нужен **жёсткий месячный кап чтений** как настройка.
3. **`MAX_TWITTER_READS_PER_MONTH` (named const/setting)** + счётчик в Redis: при достижении —
   коллектор уходит в no-op с ops-алертом (как FLOOD/quarantine у TG). Защита от счёта.
4. **Auth — app-only Bearer Token** (чтение публичных твитов не требует OAuth-user-контекста).
   → env-ключ **`TWITTER_BEARER_TOKEN`** (решение, см. §4).
5. **Граф ретвитов (C7) ДОРОГОЙ** (эндпоинты retweeters/quotes = много чтений на твит) → в MVP
   НЕ входит, выносится в post-MVP (см. §3, §6).

> Это owner-факт: реальный live-ингест Twitter будет иметь денежную стоимость. Записать в MANUAL-TODO
> и в инструкцию C6: какой доступ оформить, ожидаемые лимиты/расходы, как капить.

---

## 2. Что уже готово в коде (переиспользуем, НЕ плодим)

- **`collector/base.py` (SDK-free, ADR-001):** `SourceKind.{TELEGRAM,TWITTER}` (TWITTER = future-marker
  в enum), `SourceRef`, `PostMetrics(views,forwards,reactions, extra: Mapping[str,int])`, `RawPost`,
  `SourceCollector` Protocol (`validate_ref`, `read`). Контракт менять НЕ нужно — Twitter мапится сюда.
- **`collector/registry.py`:** lazy in-code `register/get/is_registered`; TELEGRAM зарегистрирован,
  TWITTER — нет. Добавить `register(SourceKind.TWITTER, _build_twitter_collector)`.
- **`collector/tasks.py::collect_watched_sources`:** УЖЕ source-agnostic — группирует refs `by_kind`
  и для каждого зарегистрированного kind зовёт `registry.get(kind).read(...)`. → **новый Celery-таск
  НЕ нужен**; как только TWITTER зарегистрирован и в watchlist есть twitter-refs — ингест поедет тем
  же тиком. (NB: общий per-process loop и global lock уже есть.)
- **`collector/telegram/*`:** эталон — `reader.py` (rotation/backoff внутри), `client.py` (lazy SDK),
  `mapper.py` (entity→RawPost), `dedup.py`. Twitter зеркалит структуру.
- **packs (`api/packs/data.py`):** `PackChannel(handle, kind: SourceKind)` — **уже поддерживает kind!**
  Twitter-pack = новый `PackDef` с `PackChannel(..., kind=TWITTER)`. Подписка создаёт watchlist-строки.
  → **новую сущность НЕ плодим** (C5 = данные + валидация, не код-фича).
- **pipeline/scorer:** работают на `RawPost`/`NormalizedPost` — платформо-независимы. Twitter-посты
  скорятся автоматически (C4 ≈ верификация, не разработка). Кластеризация уже кросс-источниковая
  (ADR-001 §cross-source): тема из TG и Twitter попадает в один кластер.

### Прерогативы-пробелы (НАЙДЕНЫ, входят в план)
- ⚠️ **storage `SourceKind` (storage/models/channels.py) содержит ТОЛЬКО `TELEGRAM`** — в отличие от
  `collector.base.SourceKind`. Twitter-Channel нельзя сохранить → **добавить `TWITTER` в storage
  SourceKind** (+ миграция, если колонка — нативный PG enum; проверить тип). Блокирует C5/watchlist.
- ⚠️ **watchlist handle-валидация Telegram-only** (`TELEGRAM_HANDLE_PATTERN`, '@'+4-32). Twitter
  username = 1-15 [A-Za-z0-9_]. → **per-source валидация handle** (`TWITTER_HANDLE_PATTERN`).

---

## 3. Подходы конкурентов / research к виральности и анти-накрутке

Из обзора research (arxiv 2103.03409, 2305.07384, 2305.11867; Springer SNAM 2024):
- **Co-retweet network:** пользователи, со-ретвитящие одни твиты в малых временны́х окнах = след
  координации. Высокая доля перекрытия ретвитов → подозрение на ring.
- **Rapid-retweet / rapid-semantic-similarity:** активность по близости во времени (всплеск
  одинаковых/похожих действий за секунды-минуты) — признак скоординированности.
- **Co-hashtag:** частое совместное использование одних хэштегов.
- **Account-age clustering:** много ретвитеров, созданных в один промежуток → бот-ферма.
- **Проблема ground-truth:** нет эталона «накрутка vs органика» → сигналы вероятностные, не бинарные.

Источники: [arxiv 2103.03409](https://arxiv.org/pdf/2103.03409),
[arxiv 2305.07384](https://arxiv.org/pdf/2305.07384), [Springer SNAM](https://link.springer.com/article/10.1007/s13278-024-01372-0).

### Маппинг наших TG-механик → Twitter
| Наша TG-механика | Эквивалент на Twitter |
|---|---|
| Виральность = тема расходится по **N независимым каналам** (cross_channel) | Тема расходится по **N независимым аккаунтам**; органика ≠ co-retweet-ring |
| independence-граф (каналы-форвардеры не «один автор/сетка») | independence по **co-retweet / co-hashtag / account-age** — ring душится |
| origin-tracing (кто первый запостил) | первый автор твита/первый ретвитер цепочки (conversation/referenced_tweets) |
| collusion-детекция форвард-сеток | collusion = co-retweet-сообщества (Louvain/связные компоненты на rapid-retweet-графе) |
| ad/shill-фильтр | фильтр промо/шилл-твитов (как signal/t1-adshill на TG) |

---

## 4. Зафиксированные дефолты (automode-решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| **Доступ/тариф** | X API **v2, pay-per-use** (новый дефолт 2026); legacy Basic если у владельца уже есть | фикс-тарифы закрыты; владелец оформляет, см. C6 |
| **Auth** | **app-only Bearer Token** | чтение публичных твитов не требует user-OAuth |
| **Env-ключ** | **`TWITTER_BEARER_TOKEN`** (одно имя) | префикс-платформа как `telegram_*`; совпадает с task-031 `twitter_bearer_token`; в `config.py` (optional, None-guard) + `.env.example` |
| **Эндпоинты** | `GET /2/users/by/username/:u` (validate_ref + id), `GET /2/users/:id/tweets` (`since_id`/`start_time`, `tweet.fields=public_metrics,created_at,referenced_tweets`, `max_results`) | минимальные чтения на тик |
| **Метрик-маппинг** | `like_count→reactions`, `retweet_count→forwards`, `impression_count`(fallback `0`)→`views`; `reply/quote/bookmark_count→extra` | контракт PostMetrics (int, не None); как task-031 |
| **Кадэнс** | Twitter-тик **раз в 15 мин** (отдельно от TG 60с) | read-budget §1 |
| **Лимиты чтений** | `MAX_TWITTER_READS_PER_MONTH` (setting) + Redis-счётчик; превышение → no-op + ops-алерт | защита от счёта |
| **Rate-limit/backoff** | 429/`x-rate-limit-reset` → backoff **внутри** collector (как TG FLOOD); инкапсулирован | ADR-001 invariant |
| **Дедуп** | `external_id` = tweet id, в пределах `SourceRef.kind` (как TG) | контракт RawPost |
| **handle-формат** | Twitter username без '@', 1-15 [A-Za-z0-9_]; `TWITTER_HANDLE_PATTERN` per-source | §2 пробел |
| **Лимиты планов (per-source vs суммарно)** | **суммарный `Resource.CHANNELS`** (как сейчас), зафиксировать в ADR-001 как осознанное решение | минимальный путь, избегаем over-engineering (task-031 §Discussion) |
| **Тесты** | против **замоканного API v2** (respx/fake-client); реальный X в CI НЕ дёргаем | внешняя зависимость; live-verify — owner-gated |
| **Граф ретвитов (C7)** | **post-MVP** (дорого по чтениям + сложно) | §1.5, §3 |

---

## 5. Что в MVP, что позже

**MVP (ингест + скоринг Twitter наравне с TG):**
- C1 config (env-ключ + лимиты/кадэнс как named const).
- C2 collector/twitter (client/reader/mapper/dedup, validate_ref, read; rate-limit внутри).
- C3 регистрация в registry (Celery-таск не нужен — collect_tick source-agnostic).
- C4 прогон через скоринг/буферы (верификация: Twitter-посты получают viral_score).
- C5 Twitter-pack «Crypto (RU+EN)» через packs + per-source handle-валидация + storage SourceKind.TWITTER.
- C6 инструкция по данным Twitter (docs, рус).

**Позже (post-MVP):**
- C7 retweet/quote-граф + independence/collusion/botnet-сигнал (co-retweet, rapid-retweet,
  account-age, co-hashtag). Дорого по read-budget; делать после доказанного MVP-ингеста.

---

## 6. Нарезка задач (C1–C7 → task-doc'и)

Чтобы НЕ дублировать уже существующий детальный план, переиспользуем TASK-031 как зонтик ядра:

| C-пункт | Task-doc | Статус |
|---|---|---|
| C1 config (`TWITTER_BEARER_TOKEN` + лимиты/кадэнс) | **TASK-031** (раздел config) | refreshed |
| C2 collector/twitter (client/reader/mapper/dedup) | **TASK-031** (ядро) | planned (executor-ready) |
| C3 registry + Celery (таск не нужен) | **TASK-031** | planned |
| C4 скоринг-passthrough (верификация) | **TASK-031** (DoD/G2) | planned |
| (prereq) storage SourceKind.TWITTER + per-source handle | **TASK-031** (добавлено в scope) | planned |
| C5 Twitter seed-pack «Crypto (RU+EN)» + валидация | **TASK-089** (новый) | planned, deps 031 |
| C6 инструкция по данным Twitter (docs, рус) | **TASK-090** (новый) | planned |
| C7 retweet/quote-граф + independence/collusion | **TASK-091** (новый) | deferred (post-MVP) |

Порядок исполнения ФАЗЫ C: **031 (ядро) → 089 (pack) → 090 (docs) → [091 отложен]**.
Каждая — plan→executor→verify, TDD (тесты первыми, ≥80% нового кода), surgical-дифф, PR.

### Seed-pack «Crypto (RU+EN)» — кандидаты (валидировать через `validate_ref` в C5)
EN (из исходного промпта): @VitalikButerin @balajis @saylor @APompliano @CryptoHayes @cobie
@Pentosh1 @woonomic @WClementeIII @100trillionUSD @rektcapital @CryptoKaleo @intocryptoverse
@RyanSAdams @TrustlessState @cburniske @haydenzadams @StaniKulechov @ErikVoorhees @lopp @gavofyork
@MessariCrypto @glassnode @santimentfeed @DefiLlama @lookonchain @WhaleAlert @WatcherGuru
@Cointelegraph @CoinDesk @TheBlock__
RU: @forklog @rbc_crypto @incrypted @bitsmedia_ru @prostocoin @hashtelegraph @bccnews @Cryptorussia
@profinvestment @coinpost_ru @ru_holderlab @cryptohacker_ru
> В C5 каждый прогоняется через `TwitterCollector.validate_ref()`; мёртвые/переименованные
> выкидываются с причиной (лог+отчёт); цель ~20-30 живых. Финальный список — в docs/ (RU/EN + почему).
> ⚠️ live-валидация требует реального `TWITTER_BEARER_TOKEN` → owner-gated; до ключа собираем
> список и код+моки, живой прогон — следующая итерация по появлению ключа.

---

## 7. Инварианты (соблюдать во всех C-задачах)
- Ядро `base.py`/pipeline/scorer НЕ трогаем (ADR-001). Twitter-SDK/httpx — только в `collector/twitter/`.
- `PostMetrics`: int, не None. Секреты (`TWITTER_BEARER_TOKEN`) — из env, не в коде/логах.
- Rate-limit/backoff/read-budget — внутри collector, не в `SourceCollector`-интерфейсе.
- Не ломать Telegram-путь (эталон не трогаем) и backward-compat watchlist (`source_kind` default telegram).
- Lazy registration (импорт registry без ключа side-effect-free).
