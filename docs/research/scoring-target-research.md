# Research — Валидация target-скоринга + конкурентный ландшафт

> Дата: 2026-06-16. Цель: доказать (или опровергнуть) что target-подход — Hawkes/science-фичи +
> early-window калиброванный GBDT + независимость источников — **достижим и подкреплён литературой**,
> и картировать конкурентов. Каждое неочевидное утверждение помечено: **[PROVEN]** (peer-reviewed),
> **[CLAIM]** (вендор/маркетинг), **[INFERENCE]** (наш вывод). Потребитель: [`../architecture/states/02-state-target.md`](../architecture/states/02-state-target.md).

---

## Executive summary

- Научная база **реальна и в основном peer-reviewed**, но доказывает более **узкое**, чем наивный питч.
  «Продолжит ли уже движущаяся история расти?» — предсказуемо (~0.80 acc на сбалансированной задаче).
  «Станет ли холодный пост хитом и насколько большим?» — **фундаментально ограничено** (<50% дисперсии).
  Строим под первую рамку.
- **Темпоральная скорость + структурная широта — проверенно сильнейшие фичи.** Контент и автор — слабы.
  Это прямо валидирует направление TrendPulse (кросс-канальная широта).
- **Независимость источников / кросс-комьюнити-широта = peer-reviewed предиктор органики** (Ugander 2012,
  Weng 2013) и концептуальный инверс CIB-детекта координации. Но **готового single-metric детектора
  координации end-to-end нет** — это [INFERENCE], хорошо мотивированный, не теорема.
- **Конкурентно пересечение реально не занято.** Никто не делает кросс-канальную near-dup кластеризацию
  *историй* + independence-weighted virality + быстрый алерт на crypto-RU Telegram. Santiment — ближайший.

---

## RQ1 — Hawkes / branching factor для предсказания каскадов

**n\* как ранний предиктор размера?** [PROVEN частично]. Branching factor n\* чисто классифицирует каскад:
*subcritical* (n\*<1, финальный размер замкнут в форме) vs *supercritical* (n\*>1, «взрыв», размер
**ненадёжно предсказуем**). Значит n\* — **проверенный диагностик режима предсказуемости**, надёжный
предиктор размера только в subcritical — именно НЕ в момент «вирусности».

| Модель | Данные | Окно | Результат |
|---|---|---|---|
| SEISMIC (Zhao 2015) | 1мес Twitter, 166k tweets, 34.8M reshares | 1ч (и 10мин) | ~15% rel.err @1ч; ~30% лучше конкурента |
| Mishra/Rizoiu (CIKM 2016) | Twitter NEWS | 10мин/1ч | «удвоится?» pure-Hawkes 0.70, feature 0.81, **hybrid 0.82** (rand ≈0.53) |
| TiDeH (Kobayashi 2016) | SEISMIC subset | **>12ч** (не early!) | систематическое улучшение (qual.) |
| HIP (Rizoiu 2017) | YouTube views | дни | −28.6% avg forecast err vs history |

**Ключевой вывод:** hybrid 0.82 > pure-Hawkes 0.70 → **против** чистого Hawkes-скорера, **за** Hawkes-фичи в GBDT.
**Лимиты [PROVEN]:** supercritical blind-spot; потолок <50% дисперсии (Martin&Watts 2016); нестационарность;
heavy-tailed marks; экзогенные шоки. TiDeH >12ч — **непригоден** для быстрого алерта.

## RQ2 — Early-window GBDT / feature-based

[PROVEN] для conditional/doubling-рамки. **Cheng 2014 «Can Cascades be Predicted?» (WWW)** — якорь:
- Задача: сбалансированный бинар — каскад размера *k* достигнет 2*k*? Random=50%.
- **Результат: 0.795 acc / 0.877 AUC** → 0.926/0.976 по мере наблюдения. Данные: 150,572 FB-фото, 9.23M reshares.
- **Фича-вывод [PROVEN, нагрузочный]:** только темпоральные фичи в **0.025** от all-features. Порядок:
  temporal > structural > user > content. **Широта > глубина.**

Современная GBDT-репликация (XGBoost meme-virality, arXiv:2510.05761, 2025): PR-AUC ≈0.43@30мин → ≈0.80@420мин.
Скептик-противовес [PROVEN]: Martin&Watts 2016 (<50% дисперсии), Salganik 2006 Music Lab («удача» — тот
же трек хит в одном мире, флоп в другом).

**Честная рамка:** НЕ «предсказываем вирусность с нуля». Дефендебл: «дана *начавшая* распространяться история
(первые каналы / 15–60 мин) → предсказываем продолжит ли расти, материально выше случайного, доминируют
скорость+широта».

## RQ3 — Независимость источников / координация

[PROVEN, но в двух литературах, которые не сходятся]:
- **Органика [PROVEN]:** Ugander 2012 (PNAS) — вероятность принятия «жёстко контролируется **числом
  связных компонент**» среди активных контактов; при контроле структурной диверсити размер окрестности —
  **отрицательный** предиктор. Это и есть «эффективное число независимых источников», на FB-масштабе.
  Но валидировано как предиктор adoption, не как детектор координации.
- **Координация [PROVEN как framework]:** CIB (Pacheco 2021, ICWSM) — координация = статистически
  невероятное *отсутствие* независимости (co-retweet/co-share/синхронность/контент-сходство против нуля).
  Независимость = явная нулевая гипотеза. TF-IDF «viral discounting» существует именно потому что
  органик-вирусность может выглядеть координированной (known false-positive).
- **Telegram-натив [PROVEN, 2025]:** Nature/npj Complexity (Nov 2025, ~4M EN+RU сообщений) — детект через
  **точный дубль сообщений + синхронный постинг**. Натив-трейс TG = co-forwarding/идентичный ре-броадкаст.
  **Ни одна TG-работа не операционализирует entropy/eff-source-count по имени** — открытая ниша.

**Вердикт [INFERENCE]:** «высокая независимость ⟹ органика; невероятно низкая ⟹ координация» — мотивировано
и поддержано в каждую сторону отдельно, но **не валидировано end-to-end как один детектор**. Рекомендация:
инструментировать independence *рядом* с synchrony + similarity-null, не полагаться только на диверсити.

## RQ4 — Кросс-комьюнити широта как сигнал

[PROVEN] для adoption и meme-virality:
- **Ugander 2012:** широта (число компонент) бьёт объём; объём уходит в минус при контроле широты.
- **Weng/Menczer/Ahn 2013 (Scientific Reports):** «чем больше комьюнити проникает мем, тем виральнее».
  Только первые 50 твитов, community-фичи (число заражённых комьюнити, cross-community **entropy**,
  доминирование) → **precision≈0.62 / recall≈0.42** @90-перцентиль (~7×/3.5× над random, +200–350% над
  community-blind). **Лучший single-precedent под наш подход.**
- **Zannettou 2017 «Web Centipede» (IMC):** Hawkes cross-platform influence; fringe (/pol/+The_Donald)
  гнал ~6% mainstream-news URL на Twitter. Поддерживает «fringe→mainstream = сигнал».

## RQ5 — Конкуренты

### Telegram-аналитика и social listening

| Продукт | Что мерит | Cross-channel virality / independence | Цена | TG |
|---|---|---|---|---|
| TGStat (tgstat.ru) | subs/reach/ER, citation index, репосты | Partial (репутация канала, НЕ кластеризация историй) | 3,360–34,230 ₽ | Да (глубже всех RU) |
| Telemetr (telemetr.io) | аналитика канала, post-search | Нет (search, не clustering) | $0/$25/$65/$199/$499 | Да (RU) |
| Native TG Analytics | свои каналы | Нет | Free | Свой |
| Combot | группы, модерация | Нет | Free<200 | Группы |
| Brand24 | mentions, reach, sentiment | Нет | $199–$1,499+/мес | Limited |
| Brandwatch/Meltwater/Onclusive | enterprise listening/PR | Нет | $20k–$150k+/год (quote) | Gap |

### Crypto social-signal

| Tool | Что мерит | TG ingest? | Cross-channel virality/independence | Цена |
|---|---|---|---|---|
| LunarCrush | Galaxy Score, AltRank | Нет (TG=output) | Partial (influence-weighted) | Free/~$24/~$240 (3rd-party) |
| **Santiment** | Social Volume, **Trending Stories**, on-chain | **Да (6000+ каналов вкл. TG)** | **Ближайший** — 20-мин word-spike, неформальная независимость; НЕ near-dup clustering, нет independence-weighted score | Free/**$49**/**$249** |
| The TIE | institutional sentiment | X-centric | Нет | Enterprise-opaque |
| Kaito AI | mindshare, Yaps | Да (3rd-party) | Share-of-voice, не clustering; Yaps закрыт 01.2026 | ~$99/$416/$833+ |
| Cielo/ChainEDGE | on-chain flows | TG=output | Нет (on-chain) | Cielo $59/$199 |
| Cornix/aggregators | консолидация call-каналов | Да (execution) | Нет (copy/execute) | varies |

**Caveat цен:** LunarCrush/Kaito/Brand24 — 3rd-party (офиц. страницы заблокированы), переверять перед цитированием.

### Незанятая ниша [INFERENCE, хорошо поддержан]
Пересечение **(1) per-story near-dup clustering across channels + (2) independence-weighted virality +
(3) быстрый алерт + (4) crypto-RU**: никто. TGStat/Telemetr владеют RU-TG данными, но без clustering/
independence слоя. Santiment — самый перекрывающийся incumbent (TG ingest + spike-stories + неформальная
независимость), но останавливается на **word-level** trending без productized independence-weighted score.

## RQ6 — Вердикт

**Достижимо и evidence-backed для маленькой команды — ЕСЛИ в provable-рамке:**

**Провабельно (есть peer-reviewed precedent):**
1. Early-window GBDT на velocity+breadth как *conditional growth/doubling* классификатор (Cheng 0.795/0.877; hybrid 0.82).
2. Cross-community-breadth / entropy-of-sources как фича (Weng 2013 — почти точный blueprint).
3. Hawkes n\* + endogenous/exogenous как *фичи в GBDT* (не standalone скорер).
4. Калибровка (doubling-рамка + probability calibration — стандарт, посильно).

**Аспирационно (интуитивно, но не end-to-end доказано):**
- Source-independence как *детектор координации* (доказан как предиктор органики; парить с synchrony+similarity-null).
- Абсолют «насколько виральным станет» / cold-start (потолок Martin&Watts <50%, стена «удачи» Salganik).

**Объём данных:** proven-исследования — большие корпуса (Cheng 150k/9.2M, Weng 122M, Ugander FB-масштаб). Для
*персонального niche*-детектора с balanced doubling-label нужно меньше, но ожидать **сотни–тысячи размеченных
story-каскадов** с исходами. 57.9k-корпус — стартовый, тонкий для robust CV.

**One-line:** наука поддерживает *conditional, early-window, breadth+velocity, калиброванный* скорер; whitespace
(cross-channel story clustering + source-independence на crypto-RU TG) реален и не занят. Моат дефендебл;
over-claim которого избегать — «предсказываем вирусность с нуля».

---

## Sources (ключевые URL)

**Hawkes/cascade:** arxiv.org/abs/1506.02594 · snap.stanford.edu/seismic · arxiv.org/abs/1608.04862 ·
dl.acm.org/doi/abs/10.1145/2983323.2983812 · arxiv.org/abs/1603.09449 · github.com/NII-Kobayashi/TiDeH ·
ssanner.github.io/papers/www17_hip.pdf
**Early-window GBDT/limits:** arxiv.org/abs/1403.4608 · cs.cornell.edu/home/kleinberg/www14-cascades.pdf ·
arxiv.org/abs/1602.01013 · science.org/doi/10.1126/science.1121066 · arxiv.org/abs/2510.05761 · arxiv.org/abs/1812.06034
**Independence/coordination:** pnas.org/doi/10.1073/pnas.1116502109 · arxiv.org/abs/2001.05658 ·
ojs.aaai.org/index.php/ICWSM/article/view/18075 · arxiv.org/abs/2408.01257 · nature.com/articles/s44260-025-00056-w
**Cross-community:** nature.com/articles/srep02522 · arxiv.org/abs/1306.0158 · conferences.sigcomm.org/imc/2017/papers/imc17-final145.pdf
**Конкуренты:** tgstat.ru/en/p/prices · telemetr.io/en/pricing · santiment.net · app.santiment.net/pricing ·
academy.santiment.net/sanbase/social-trends · lunarcrush.com · kaito.ai · brand24.com/blog/telegram-analytics-tools

**Caveat качества источников:** часть SEISMIC-чисел сверена через SNAP + вторичный обзор; TiDeH без единого
verified headline-числа; LunarCrush/Kaito/Brand24 цены 3rd-party — переверять перед внешним цитированием.
</content>
