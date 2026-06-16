# Twitter-source + prod-verify + TG-AuthKey-fix — autonomous /loop prompt

Вставить в Claude Code: `/loop` и следом весь блок ниже (интервал не указывать — loop сам себя пейсит).

---

```
/loop

РЕЖИМ: автономный automode. НЕ задавай мне вопросов. На любой развилке выбирай разумный
дефолт, фиксируй его в ## Discussion task-doc и продолжай. Единственное, что делаю я, владелец —
кладу API-ключ Twitter/X в окружение и (по запросу из MANUAL-TODO) перевыпускаю TG-сессию.
Всё остальное планируешь, пишешь, тестируешь и верифицируешь сам. Язык артефактов и отчётов —
русский, код и коммиты — как в репозитории.

РАБОЧАЯ ДИРЕКТОРИЯ: apps/trendPulse. Документный vault (docs/CLAUDE.md, docs/CODEMAPS/*,
docs/CONVENTIONS.md, ADR) — единственный источник истины, не выдумывай паттерны из общих знаний.

ДВИЖОК ЦИКЛА: для каждой surgical-задачи прогоняй конвейер
  /next:trendpulse-plan  →  /next:trendpulse-executor  →  /next:trendpulse-verify
(классические skills trendpulse-plan/executor/verify взаимозаменяемы — общий task-doc контракт).
Планировщик НЕ должен спрашивать меня: продуктовые развилки решай дефолтом и пиши в ## Discussion.
Каждая задача = отдельный task-doc в docs/tasks/, обновляй docs/tasks/tasks-index.md.

СОСТОЯНИЕ И ОЧИСТКА КОНТЕКСТА МЕЖДУ ЗАДАЧАМИ (важно):
- Веди cache/twitter-source-loop-state.md (текущая фаза, сделанные задачи, PR, открытые
  MANUAL-TODO) и cache/twitter-source-loop.md (лог итераций).
- ПОСЛЕ КАЖДОЙ ЗАДАЧИ очищай рабочий контекст: запиши всё нужное в state-файл и task-doc, затем
  стартуй следующую задачу с ЧИСТОГО контекста, опираясь ТОЛЬКО на cache/*-state.md + task-doc +
  vault, а не на историю переписки. Не таскай транскрипт прошлых задач между итерациями.
- НЕ трогай живую owner-сессию Telegram-пула и НЕ реюзай pool-сессию ни для какого backfill
  (см. память trendpulse-tg-session-incident — это и есть причина инцидента ниже).

ЗАДАЧИ ИДУТ СТРОГО ПО ПОРЯДКУ ФАЗ; каждая — через plan→executor→verify.

══════════════════════════════════════════════════════════════════════
ФАЗА 0 — PROD-CRITICAL: ПОЧИНИТЬ AuthKeyDuplicatedError + СПАМ АЛЕРТОВ
══════════════════════════════════════════════════════════════════════
Симптом: в ops-TG-канал «по кд» сыпется `TG pool: account error on entity resolve
(AuthKeyDuplicatedError)`. Корень: backend/src/collector/telegram/reader.py (~196-201) при
non-flood ошибке резолва шлёт alert reason=auth_error и кидает SourceUnavailableError, но
аккаунт НЕ выселяется из пула. AuthKeyDuplicatedError = одна сессия используется двумя клиентами
одновременно → Telegram НАВСЕГДА инвалидирует ключ. Каждый цикл чтения снова берёт ту же мёртвую
сессию → снова ошибка → снова алерт. Throttle по reason=auth_error не давит спам (вероятно из-за
Redis OOM/эвикции throttle-ключа).
Сделать (можно разбить на несколько surgical-задач):
  1. Различать AuthKeyDuplicatedError (и родственные перманентные auth-ошибки: AuthKeyError,
     UserDeactivated, SessionRevoked) от транзиентных. На перманентной — КВАРАНТИН/выселение
     этого аккаунта из AccountPool (account_pool.py), чтобы пул больше его не выдавал и не
     долбился в мёртвую сессию.
  2. Алерт по такому аккаунту — РОВНО ОДИН раз (per-account reason-ключ + длинный cooldown), с
     явным текстом «сессия X мертва (AuthKeyDuplicated), перевыпусти». Никакого секрета/строки
     сессии в тексте. Спам прекратиться должен даже при деградации Redis (throttle не должен
     зависеть только от эвиктируемого ключа — добей надёжность дедупа).
  3. Найти и закрыть ПЕРВОПРИЧИНУ совместного использования сессии (двойной клиент / backfill на
     pool-сессии / перезапуск без graceful disconnect). Гарантировать single-owner-per-session.
  4. В MANUAL-TODO выписать владельцу: какие сессии надо перевыпустить.
Verify: запустить collector, убедиться что мёртвый аккаунт выселен, алерт пришёл один раз и спам
прекратился, живые аккаунты пула продолжают ингест, Redis без OOM. Без этого ФАЗА 0 не закрыта.

══════════════════════════════════════════════════════════════════════
ФАЗА A — ВЕРИФИКАЦИЯ PROD (бэклог T0–T8 уже задеплоен, PR #135–#145)
══════════════════════════════════════════════════════════════════════
1. Здоровье prod: все сервисы up, свежий ingest, viral_score>0, Redis без OOM, TG-сессия healthy,
   серт SAN на обоих доменах (сверься с памятью trendpulse-launch-state).
2. MCP-сервер и REST /v1/signals (фича T7) РЕАЛЬНО доступны через edge-nginx снаружи end-to-end:
     - реальный HTTPS-запрос к /api/v1/signals через nginx → валидный ответ;
     - реальная MCP-сессия через nginx (хендшейк + вызов инструмента signals);
     - если MCP по SSE/стриму — в nginx для маршрута выставить proxy_buffering off,
       достаточный proxy_read_timeout, стрим не должен рваться.
   Сломанный маршрут/таймауты/буферизацию чинить как surgical-задачу в
   release/provisioning/nginx/templates/nginx.conf.template (+ dev-аналог) и верифицировать живым
   MCP-вызовом через nginx. Без живого end-to-end MCP-вызова ФАЗА A не закрыта.
3. Прочие prod-дефекты — отдельными surgical-задачами.

══════════════════════════════════════════════════════════════════════
ФАЗА B — ИССЛЕДОВАНИЕ И ПЛАН TWITTER/X КАК ИСТОЧНИКА
══════════════════════════════════════════════════════════════════════
1. Изучи код источников: backend/src/collector/ (base.py: SourceRef/SourceCollector/validate_ref,
   registry.py, buffer.py, tasks.py), эталон backend/src/collector/telegram/* и фичу packs
   (backend/src/api/packs/*) — шаблоны для коллектора и коллекции аккаунтов. SourceKind.TWITTER
   уже есть в enum как future-marker (ADR-001).
2. Изучи доку: ADR по source-абстракции, CODEMAPS коллектора/скоринга/packs, CONVENTIONS.
3. Изучи подходы конкурентов к ингесту виральности из Twitter/X и сетевому анти-накрут анализу
   (retweet/quote-граф, origin-tracing первого автора, ботнет/collusion-детекция, кросс-аккаунтная
   виральность). Краткий research-бриф в docs/, выбери что в MVP, что позже. Маппинг наших
   TG-механик (independence/collusion-граф, origin-tracing) на Twitter.
4. Нарежь работу на минимальный набор surgical-задач. Реши дефолтом и зафиксируй: какой Twitter/X
   API/тариф, имя env-переменной ключа (например X_BEARER_TOKEN или TWITTER_BEARER_TOKEN — выбери
   одно, пропиши в config.py через pydantic-settings и в .env.example), модель данных/метрик,
   дедуп, rate-limit/backoff, маппинг в общий формат поста. НЕ ломай Telegram-путь и контракт
   SourceCollector.

══════════════════════════════════════════════════════════════════════
ФАЗА C — РЕАЛИЗАЦИЯ TWITTER-ИСТОЧНИКА (итеративно, по одной задаче)
══════════════════════════════════════════════════════════════════════
Каждая задача: plan → executor → verify, surgical-диф, TDD (тесты первыми, ≥80% покрытие нового
кода), затем PR. Нарезка (уточни в Фазе B):
  C1. config: env-ключ X/Twitter + настройки (TTL/таймауты/лимиты как именованные константы).
  C2. backend/src/collector/twitter/*: client, reader, mapper, dedup по образцу telegram/*,
      включая TwitterCollector.validate_ref() — true iff @handle публичен/читаем (аналог
      telegram reader.validate_ref, никогда не пробрасывает исключение наружу).
  C3. регистрация TWITTER в registry.py (ленивая фабрика) + Celery-таск ингеста как у TG.
  C4. прогон через скоринг/буферы: посты Twitter получают viral_score наравне с TG.
  C5. TWITTER-КОЛЛЕКЦИЯ (АНАЛОГ TG CHANNELS): собрать pack из Twitter-аккаунтов ровно как pack из
      TG-каналов. Аккаунт = SourceRef(kind=TWITTER, handle=@...). Перед добавлением в pack —
      провалидировать каждый через TwitterCollector.validate_ref(); невалидные отсечь с понятной
      причиной (лог + отчёт). Переиспользуй существующую packs-фичу (backend/src/api/packs/*) —
      packs должны принимать Twitter-refs наравне с TG, новую сущность НЕ плодить.
      Собери дефолтный seed-pack «Crypto (RU+EN)» из кандидатов ниже. Это КАНДИДАТЫ — прогони
      каждого через validate_ref, оставь только живых, переименованных/мёртвых выкинь и перечисли
      в отчёте. Цель ~20-30 живых суммарно.
        EN: @VitalikButerin @balajis @saylor @APompliano @CryptoHayes @cobie @Pentosh1 @woonomic
            @WClementeIII @100trillionUSD @rektcapital @CryptoKaleo @intocryptoverse @RyanSAdams
            @TrustlessState @cburniske @haydenzadams @StaniKulechov @ErikVoorhees @lopp @gavofyork
            @MessariCrypto @glassnode @santimentfeed @DefiLlama @lookonchain @WhaleAlert
            @WatcherGuru @Cointelegraph @CoinDesk @TheBlock__
        RU: @forklog @rbc_crypto @incrypted @bitsmedia_ru @prostocoin @hashtelegraph @bccnews
            @Cryptorussia @profinvestment @coinpost_ru @ru_holderlab @cryptohacker_ru
      Финальный валидированный список pack'а зафиксируй в docs/ (пометки RU/EN + почему выбран).
      Verify: создать pack из реальных аккаунтов, провалидировать, запустить ингест по pack'у,
      увидеть посты со скором.
  C6. ИНСТРУКЦИЯ ПО ДАННЫМ TWITTER (docs/, на русском): как получить нужные данные из Twitter/X —
      какой доступ/тариф API оформить, как выпустить ключ/токен, под каким именем env-переменной
      положить, какие endpoint'ы/поля используем, лимиты, как добавить аккаунты в pack.
  C7. (если влезает в MVP по Фазе B) retweet/quote-граф + ботнет/independence-сигнал.

ОБРАЩЕНИЕ С КЛЮЧОМ: я кладу ключ в окружение под выбранным именем. Код читает ключ из config. На
verify, если живой ключ ещё не выставлен — НЕ спрашивай и НЕ блокируйся: пометь именно живой
behavioral-чек как owner-blocked MANUAL-TODO, доведи код+юнит/интеграционные тесты (с моками
клиента) до зелёного и иди дальше. Когда ключ появится — на следующей итерации добей живой
end-to-end: провалидировать реальные аккаунты, собрать pack, заингестить, увидеть viral_score.

КРИТЕРИЙ ЗАВЕРШЕНИЯ ЦИКЛА:
  ✓ ФАЗА 0: AuthKeyDuplicated починен, мёртвые сессии выселяются, алерт-спам прекращён,
    первопричина закрыта, MANUAL-TODO на перевыпуск сессий выписан.
  ✓ ФАЗА A: prod здоров, MCP + /v1/signals подтверждены живым вызовом через nginx.
  ✓ ФАЗА B: research-бриф и набор task-doc'ов написаны.
  ✓ ФАЗА C: Twitter зарегистрирован как источник и ингестит; посты скорятся; pack из
    провалидированных Twitter-аккаунтов собирается как из TG-каналов; написана инструкция по
    данным Twitter; тесты зелёные; PR'ы открыты. Остаток допустим только owner-blocked живой
    Twitter-чек, ждущий ключа (явно в MANUAL-TODO).

ФИНАЛЬНОЕ РЕЗЮМЕ (в конце обязательно): выведи сводку по всем фазам — что починено/построено,
полный список PR (номер + одна строка), что задеплоено/смержено, открытые MANUAL-TODO для меня
(перевыпуск сессий, Twitter-ключ и т.д.), известные ограничения и следующий шаг. Обнови
соответствующую память trendpulse-*. После резюме заверши цикл.
```
