"""Unit tests for the GBDT serving plumbing in the live scorer (TASK-125).

These tests exercise the OPTIONAL serving path wired into `scorer.tasks`:
- `_early_features_from_inputs` (pure mapping `ScoreInputs -> EarlyFeatures`),
- `_load_viral_model` (lazy, graceful model loading behind the config flag),
- `_persist_score` shadow-logging of `select_prediction`'s `model_choice` + `p_grow`,
  WITHOUT changing the persisted `viral_score` (which stays the v2 formula).

The serving path is DORMANT by default (`scorer_model_enabled=False`): the golden
byte-identity test (AC1) proves that with the flag OFF the persisted score is exactly
the v2 formula value, with no `select_prediction`/lightgbm effect.

A fake booster keeps these tests free of the optional `lightgbm` dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from scorer.score import (
    BURST_FLOOR_HOURS,
    ScoreInputs,
    compute_components,
    engagement_numerator,
)
from scorer.tasks import _early_features_from_inputs, _load_viral_model, _persist_score
from scorer.viral_model import (
    FEATURE_ORDER,
    EarlyFeatures,
    GbdtViralModel,
    ModelChoice,
    ViralModel,
)


def _bound_upsert_values(session: MagicMock) -> dict[str, object]:
    """Extract the values BOUND into the `pg_insert(...).values(...)` upsert statement.

    `_persist_score` issues exactly one `session.execute(stmt)`; `stmt` is a PostgreSQL
    `Insert`. Compiling it against the PG dialect surfaces the bound parameters, so the
    test can assert the persisted `viral_score`/components are the golden formula values
    (proving "shadow-only, stored score unchanged" as a hard binding assertion, not just
    that an upsert happened).
    """
    call = session.execute.call_args
    assert call is not None, "an upsert must have been issued"
    stmt = call.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    return dict(compiled.params)


def _inputs(
    *,
    views: int = 1000,
    forwards: int = 10,
    reactions: int = 20,
    delta_channel_count: int = 3,
    delta_hours: float = 2.0,
    unique_channels_count: int = 3,
    watched_channels_count: int = 5,
) -> ScoreInputs:
    """Build a fixed `ScoreInputs` (no event stream → aggregate path)."""
    return ScoreInputs(
        views=views,
        forwards=forwards,
        reactions=reactions,
        channel_avg=1.0,
        delta_channel_count=delta_channel_count,
        delta_hours=delta_hours,
        unique_channels_count=unique_channels_count,
        watched_channels_count=watched_channels_count,
    )


@dataclass(frozen=True)
class _StubModel:
    """A `ViralModel` stub returning a fixed probability (mirrors a loaded GBDT)."""

    fixed: float

    def predict_proba(self, features: EarlyFeatures) -> float:
        return self.fixed


# --- AC4: feature mapping correctness ------------------------------------------------


@pytest.mark.unit
def test_early_features_mapping_hand_computed() -> None:
    """`_early_features_from_inputs` maps each field per the Discussion contract."""
    # posts: the live path passes len(posts) via unique-channel + post aggregates;
    # here the mapping uses unique_channels_count for e_ch and an explicit e_posts.
    inputs = _inputs(
        views=1000,
        forwards=10,
        reactions=20,
        unique_channels_count=4,
        delta_hours=2.0,
    )
    feats = _early_features_from_inputs(inputs, post_count=7)

    expected_eng = math.log1p(engagement_numerator(views=1000, forwards=10, reactions=20))
    assert feats.e_ch == 4.0
    assert feats.e_posts == 7.0
    assert feats.e_eng_log == pytest.approx(expected_eng)
    assert feats.e_burst == pytest.approx(4.0 / max(2.0, BURST_FLOOR_HOURS))


@pytest.mark.unit
def test_early_features_burst_floor_on_zero_delta() -> None:
    """delta_hours == 0 → e_burst uses the 1h floor, never divides by zero."""
    inputs = _inputs(unique_channels_count=2, delta_hours=0.0)
    feats = _early_features_from_inputs(inputs, post_count=2)
    assert feats.e_burst == pytest.approx(2.0 / BURST_FLOOR_HOURS)
    assert math.isfinite(feats.e_burst)


@pytest.mark.unit
def test_early_features_constructs_valid_for_realistic_inputs() -> None:
    """The mapping never trips the `EarlyFeatures` non-negative/finite validator."""
    feats = _early_features_from_inputs(_inputs(), post_count=5)
    assert isinstance(feats, EarlyFeatures)
    assert feats.as_vector() == [feats.e_ch, feats.e_posts, feats.e_eng_log, feats.e_burst]


# --- AC5 / AC6: _load_viral_model graceful + lazy -----------------------------------


@pytest.mark.unit
def test_load_viral_model_disabled_returns_none() -> None:
    """Flag OFF (default) → no model loaded, lightgbm never imported."""
    settings = MagicMock()
    settings.scorer_model_enabled = False
    settings.scorer_model_path = ""
    assert _load_viral_model(settings) is None


@pytest.mark.unit
def test_load_viral_model_enabled_empty_path_returns_none() -> None:
    """Flag ON but empty path → None (nothing to load), no raise."""
    settings = MagicMock()
    settings.scorer_model_enabled = True
    settings.scorer_model_path = ""
    assert _load_viral_model(settings) is None


@pytest.mark.unit
def test_load_viral_model_missing_file_returns_none(tmp_path: Path) -> None:
    """Flag ON + non-existent artifact → None + warning, never raises into the tick."""
    settings = MagicMock()
    settings.scorer_model_enabled = True
    settings.scorer_model_path = str(tmp_path / "does-not-exist.txt")
    assert _load_viral_model(settings) is None


@pytest.mark.unit
def test_load_viral_model_loads_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag ON + present artifact → GbdtViralModel.load is called with FEATURE_ORDER."""
    settings = MagicMock()
    settings.scorer_model_enabled = True
    settings.scorer_model_path = "/tmp/model.txt"

    sentinel = _StubModel(fixed=0.5)
    captured: dict[str, object] = {}

    def _fake_load(model_path: Path, *, feature_order: tuple[str, ...]) -> ViralModel:
        captured["path"] = model_path
        captured["feature_order"] = feature_order
        return sentinel

    monkeypatch.setattr(GbdtViralModel, "load", staticmethod(_fake_load))
    loaded = _load_viral_model(settings)
    assert loaded is sentinel
    assert captured["path"] == Path("/tmp/model.txt")
    assert captured["feature_order"] == FEATURE_ORDER


# --- AC1: golden OFF byte-identity ---------------------------------------------------


@pytest.mark.unit
def test_persist_score_off_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag OFF (gbdt=None) → persisted score == compute_components(inputs) exactly.

    Golden proof: the value `_persist_score` returns and the component values written
    are EXACTLY `compute_components(inputs)` — `select_prediction`/log_event are never
    invoked when no model is loaded.
    """
    inputs = _inputs()
    golden = compute_components(inputs)

    session = MagicMock()
    select_called = MagicMock()
    logged: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr("scorer.tasks.select_prediction", select_called)
    monkeypatch.setattr(
        "scorer.tasks.log_event",
        lambda event, **fields: logged.append((event, fields)),
    )

    returned = _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, gbdt=None)

    assert returned == golden.viral_score
    select_called.assert_not_called()
    assert not any(event == "model_choice" for event, _ in logged)

    # HARD assertion: the values BOUND into the upsert must be the golden formula
    # components — not merely that an upsert happened.
    bound = _bound_upsert_values(session)
    assert bound["viral_score"] == pytest.approx(golden.viral_score)
    assert bound["velocity"] == pytest.approx(golden.velocity)
    assert bound["engagement"] == pytest.approx(golden.engagement)
    assert bound["cross_channel"] == pytest.approx(golden.cross_channel)


# --- AC2: flag ON + loadable model → GBDT choice logged, score still formula ---------


@pytest.mark.unit
def test_persist_score_on_logs_gbdt_choice_without_changing_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + model + ≥2post/≥2channel → GBDT prob logged (shadow); score formula."""
    inputs = _inputs(unique_channels_count=3, delta_channel_count=3)
    golden = compute_components(inputs)
    known_prob = 0.77

    session = MagicMock()
    logged: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "scorer.tasks.log_event",
        lambda event, **fields: logged.append((event, fields)),
    )

    returned = _persist_score(
        session,
        user_id=11,
        cluster_id=22,
        inputs=inputs,
        gbdt=_StubModel(fixed=known_prob),
        post_count=4,
    )

    # viral_score persisted/returned is STILL the formula value (shadow-only).
    assert returned == golden.viral_score

    # HARD assertion: the GBDT shadow run did NOT change the value BOUND into the upsert
    # — the stored score stays exactly the golden formula components.
    bound = _bound_upsert_values(session)
    assert bound["viral_score"] == pytest.approx(golden.viral_score)
    assert bound["velocity"] == pytest.approx(golden.velocity)
    assert bound["engagement"] == pytest.approx(golden.engagement)
    assert bound["cross_channel"] == pytest.approx(golden.cross_channel)

    model_choice_events = [fields for event, fields in logged if event == "model_choice"]
    assert len(model_choice_events) == 1
    fields = model_choice_events[0]
    assert fields["choice"] == ModelChoice.GBDT.value
    assert fields["p_grow"] == pytest.approx(known_prob)
    assert 0.0 <= float(fields["p_grow"]) <= 1.0


# --- AC3: flag ON + cold-start cluster → FALLBACK choice -----------------------------


@pytest.mark.unit
def test_persist_score_on_cold_start_logs_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + model but <2 channels → FALLBACK choice (formula pseudo-prob)."""
    inputs = _inputs(unique_channels_count=1, delta_channel_count=1)
    golden = compute_components(inputs)

    session = MagicMock()
    logged: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "scorer.tasks.log_event",
        lambda event, **fields: logged.append((event, fields)),
    )

    returned = _persist_score(
        session,
        user_id=1,
        cluster_id=2,
        inputs=inputs,
        gbdt=_StubModel(fixed=0.99),  # would be used only if min-signal cleared
        post_count=1,
    )

    assert returned == golden.viral_score
    model_choice_events = [fields for event, fields in logged if event == "model_choice"]
    assert len(model_choice_events) == 1
    assert model_choice_events[0]["choice"] == ModelChoice.FALLBACK.value


# --- Resilience: a shadow model failure NEVER breaks the scoring path ----------------


@dataclass(frozen=True)
class _RaisingModel:
    """A `ViralModel` whose `predict_proba` raises a RAW (non-domain) RuntimeError.

    Mirrors a misbehaving lightgbm booster: it does NOT raise `ViralModelError`, so an
    unguarded shadow block would propagate it up and abort the user's scoring loop.
    """

    def predict_proba(self, features: EarlyFeatures) -> float:
        raise RuntimeError("boom: raw booster failure")


@pytest.mark.unit
def test_persist_score_shadow_failure_does_not_break_scoring() -> None:
    """A gbdt whose predict_proba raises RuntimeError → no raise; formula score persists.

    Enforces the task invariant: model failure (load or predict) NEVER breaks the
    scoring/alert path. FAILS before the shadow-block guard (the RuntimeError propagates),
    PASSES after (it is logged best-effort and the formula score is stored/returned).
    """
    inputs = _inputs(unique_channels_count=3, delta_channel_count=3)
    golden = compute_components(inputs)
    session = MagicMock()

    returned = _persist_score(
        session,
        user_id=7,
        cluster_id=9,
        inputs=inputs,
        gbdt=_RaisingModel(),
        post_count=4,
    )

    # No exception escaped; the persisted/returned score is the formula value.
    assert returned == golden.viral_score
    bound = _bound_upsert_values(session)
    assert bound["viral_score"] == pytest.approx(golden.viral_score)
