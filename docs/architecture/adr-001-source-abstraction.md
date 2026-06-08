# ADR-001 — Source abstraction (multi-source ready: Telegram now, Twitter/X later)

- Status: **Accepted**
- Date: 2026-06-08
- Context: [high-level-architecture.md](./high-level-architecture.md)

## Context

MVP мониторит публичные Telegram-каналы. Roadmap (overview §9, Фаза 2) добавляет Twitter/X как второй источник и далее, возможно, другие. Если коллектор и pipeline жёстко завязать на Telethon/Telegram-модель данных, добавление источника = переписывание pipeline и scorer. Нужна абстракция источника **с первого дня**, при этом без оверинжиниринга под несуществующие платформы.

## Decision

Вводим единый порт `SourceCollector` и нормализованную доменную модель `RawPost`, к которым адаптируется любой источник. Pipeline (dedup→normalize→embed→cluster) и scorer работают **только** с `RawPost`/`NormalizedPost` и ничего не знают о платформе.

```python
# collector/base.py  (иллюстративно)
class SourceKind(StrEnum):
    TELEGRAM = "telegram"
    TWITTER  = "twitter"   # future

@dataclass(frozen=True)
class SourceRef:               # что мониторим: канал/аккаунт/хэштег
    kind: SourceKind
    handle: str                # "@channel", "@user", "#tag"

@dataclass(frozen=True)
class RawPost:                 # нормализованный пост из любого источника
    source: SourceRef
    external_id: str           # id поста в платформе (для дедупа в рамках источника)
    author: str
    text: str
    media_hashes: tuple[str, ...]
    metrics: PostMetrics       # views, forwards, reactions/likes, …
    posted_at: datetime        # tz-aware UTC
    fetched_at: datetime

class SourceCollector(Protocol):
    kind: SourceKind
    async def validate_ref(self, ref: SourceRef) -> bool: ...
    async def read(self, refs: list[SourceRef], since: datetime) -> AsyncIterator[RawPost]: ...
    # rate-limit / backoff / account-rotation инкапсулированы внутри реализации
```

- **Telegram-реализация (сейчас):** `collector/telegram/` — Telethon, пул технических аккаунтов, `FLOOD_WAIT` backoff + ротация, маппинг Telegram-сущностей → `RawPost`.
- **Реестр коллекторов:** `collector/registry.py` маппит `SourceKind → SourceCollector`; добавление источника = регистрация новой реализации, апстрим не меняется.
- **`metrics` нормализуются** к общему виду (`engagement` считается из них), чтобы scorer был платформо-независим. Платформо-специфичные поля живут в `metrics.extra`.
- **Watchlist хранит `SourceRef` с `kind`** — schema готова к мульти-источнику с самого начала (поле `source_kind`, default `telegram`).
- **Cross-source кластеризация** (Фаза 2 «cross-platform viral score»): кластеризатор уже оперирует векторами `NormalizedPost`, поэтому посты из Telegram и Twitter про одну тему попадают в один кластер без изменений ядра.

## Scope guard (no overengineering)

- Реализуем **только Telegram** сейчас. Twitter/X — пустой контракт не пишем; достаточно того, что интерфейс + модель данных + schema (`source_kind`) не привязаны к Telegram.
- Не вводим плагинную загрузку/конфиг-DSL — простой in-code registry.

## Consequences

- (+) Новый источник изолирован в `collector/<kind>/`; pipeline/scorer/scoring/API не трогаются.
- (+) Watchlist и БД с первого дня мульти-источниковые (миграции не ломаются при добавлении Twitter).
- (+) Тестируемость: pipeline тестируется на `RawPost`-фикстурах без Telegram.
- (−) Небольшой оверхед маппинга платформа→`RawPost` на каждый источник.
- Влияет на задачи: **task-005** (collector+abstraction), **task-002** (schema `source_kind`), **task-007** (pipeline на `RawPost`), **task-008** (scorer на нормализованных metrics).
