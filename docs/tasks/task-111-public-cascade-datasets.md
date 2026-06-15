# TASK-111 — B3 bootstrap public cascade datasets

**Track:** B (data) → C (ML), step B3. **Depends on:** TASK-108 (B0 gate), TASK-110 (B2 split/label/metrics).

## Goal

B0 showed only ~315 (1.66%) genuinely-multi-channel quality TG stories survive the gate, so the OFFLINE GBDT (C1) is N-LIMITED on TG data alone. Public temporal-cascade datasets supply training VOLUME mapped to the SAME early-window feature schema the B2 harness consumes, validating the methodology at scale and giving C1 enough N.

## What was built

**Typed loader + mapper** (`eval_offline/public_datasets.py`, mypy --strict clean, no `Any`):
- `CascadeEvent` (frozen, validated), `HiggsInteraction` enum (RT/RE/MT, weighted 3/2/1 mirroring TG forward/reaction/view), `parse_higgs_line` / `load_higgs` (boundary-validated parsing).
- `group_cascades` — groups the flat interaction stream into cascades keyed by target (the item being spread), time-ordered.
- `map_cascade` / `map_higgs_to_b2` — projects each cascade into the B2 contract: a `eval.forward_split.ClusterOutcome` (birth + future weighted-engagement outcome) + a `CascadeFeatures` early-window vector (e_ch/e_posts/e_eng_log/e_burst) measured over `[birth, birth+T_obs]` only. `min_cascade_size` is the public-data analogue of the B0 too_small/single_channel gate. Leak-free by construction (features early-only, outcome never fed back).
- `bootstrap_status()` — the dataset-availability log.

**Validation harness** (`eval_offline/harness_b3_public.py`): runs the EXACT B2 split + Cheng doubling/top-quartile label + PR-AUC sweep on the Higgs cascades — proving the methodology transfers.

**Committed sample** (`eval_offline/data_public/higgs_activity_sample.txt`, 5k rows, 128KB). Full file (`eval_offline/data/higgs-activity_time.txt`, 563k rows) gitignored under `data/`.

## Dataset bootstrap status

| Dataset | Status | Why |
|---|---|---|
| **Higgs Twitter** (snap.stanford.edu) | **WORKING** | 563,069 timestamped activities, free direct download (~4MB gz); 59,977 distinct targets → 36,020 cascades (>=2 interactions) |
| Pushshift Telegram (zenodo 3607497) | SKIPPED | `messages.ndjson.zst` is ~52GB (infeasible to bootstrap offline); `channels`(7MB)/`accounts`(125MB) metadata carry no per-message cascade timing |
| Weibo / DeepHawkes (github CaoQi92) | SKIPPED | repo ships code only; the cascade dataset is behind a manual Google-Drive/Baidu download (no direct URL / needs manual auth) |
| MemeTracker (snap.stanford.edu) | SKIPPED | monthly phrase-cluster files are GB-scale; no small official sample slice (sample URL 404s) |

One temporal-cascade dataset (Higgs, the prompt's priority target) is fully working; the other three are logged as skipped with concrete reasons, per the "log and proceed" instruction.

## Results — B2 methodology validated on Higgs (36,020 cascades, vs 964 gated TG stories)

Doubling label (cohort 1h, 6h gap, test n=5,574, ~46% positive), best early feature `e_eng_log`:

| T_obs | e_eng_log PR-AUC | e_eng_log ROC-AUC | e_ch PR-AUC |
|---|---|---|---|
| 15m | 0.869 | 0.848 | 0.777 |
| 30m | 0.908 | 0.901 | 0.810 |
| 1h  | **0.939** | **0.945** | 0.841 |
| 3h  | 0.922 | 0.935 | 0.829 |
| 6h  | 0.902 | 0.919 | 0.811 |

The B2 forward-split + balanced-doubling methodology transfers cleanly to a 36k-cascade public dataset: PR-AUC rises with the early window, peaks ~1h, then plateaus (late observation adds little). This is the VOLUME substrate C1 trains on (the gated TG subset is too thin alone). Top-quartile (rarer positives): e_eng_log PR-AUC 0.78 @15m → 0.85 @1h.

## Verification
- 11 unit tests (`eval_offline/test_public_datasets.py`), hand-computed (grouping, early-window features, outcome, min-size filter, validation).
- `public_datasets.py` + `harness_b3_public.py` mypy --strict clean (no `Any`); ruff (backend select set E/F/W/I/B/UP/SIM/RUF/TID) clean.
- Big raw file gitignored; 5k sample committed; loader reproducible.
