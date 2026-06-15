"""C1 — GBDT virality model behind a clean typed interface, with a formula fallback.

TASK-112 (Track B→C / C1). The hand-tuned v2 formula (`scorer.score.compute_viral_score`)
ranks eventual virality at PR-AUC ~0.6-0.75 on the thin B0-gated TG subset and ~0.94 on
the 36k-cascade Higgs volume (B2/B3 harnesses). C1 replaces the *ranking* with a GBDT
that consumes the SAME B1/B2 early-window feature vector and emits a CALIBRATED
probability — but only when the cluster has accrued enough early signal. Below that
floor the model is unreliable (cold-start), so the scorer FALLS BACK to the v2 formula.

Design (owner rules: real types, runtime validation, no `Any`):

- `EarlyFeatures` — the frozen, validated early-window vector (the B1 snapshot shape +
  the B2 harness feature names). The single contract both training and inference share.
- `ViralModel` — a `Protocol`: `predict_proba(EarlyFeatures) -> float` in [0, 1].
- `FormulaFallbackModel` — wraps the deterministic v2 formula, normalising its 0-100
  output into a [0, 1] pseudo-probability. The cold-start / always-available baseline.
- `GbdtViralModel` — loads a LightGBM booster (from its native text dump, so loading
  needs no pickle and the artifact is reviewable) + the EXACT feature order it was
  trained on, and predicts a calibrated probability. LightGBM is imported LAZILY so the
  backend image / CI does not require it unless a model is actually loaded.
- `select_prediction` — the policy: use the GBDT when `EarlyFeatures` clears the
  minimum-signal floor, else fall back. Returns WHICH model produced the score so the
  caller can log/measure the split.

This module performs NO I/O at import and queries no DB; `GbdtViralModel.load` is the
only filesystem touch and is explicit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from scorer.score import ScoreInputs, compute_viral_score

# The model's feature order — the SINGLE source of truth shared by training (offline)
# and inference. A loaded GBDT artifact must declare exactly this list (validated on
# load) so a re-ordered or stale model can never be silently mis-fed.
FEATURE_ORDER: tuple[str, ...] = (
    "e_ch",  # distinct early channels / sources (breadth)
    "e_posts",  # early post / interaction count
    "e_eng_log",  # log1p(weighted early engagement)
    "e_burst",  # early breadth per hour (spread speed)
)

# Minimum early signal for the GBDT to be trusted. Below this a cluster is effectively
# a cold-start singleton/pair and the model extrapolates poorly → fall back to v2.
_MIN_POSTS_FOR_MODEL = 2
_MIN_CHANNELS_FOR_MODEL = 2

# v2 formula output is 0-100; divide by this to map it into a [0, 1] pseudo-probability
# for a uniform `ViralModel` contract (the fallback is a RANKING signal, not calibrated).
_FORMULA_SCALE = 100.0


class ViralModelError(ValueError):
    """A model input / artifact was malformed (bad features, missing/old artifact)."""


@dataclass(frozen=True)
class EarlyFeatures:
    """Leak-free early-window feature vector (B1 snapshot shape / B2 harness names).

    Validated at construction (never trust external data). Every field is non-negative;
    `e_eng_log` is already log1p-compressed and `e_burst` is a rate, so both are floats.
    """

    e_ch: float
    e_posts: float
    e_eng_log: float
    e_burst: float

    def __post_init__(self) -> None:
        for name in FEATURE_ORDER:
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ViralModelError(f"{name} must be finite and >= 0, got {value}")

    def as_vector(self) -> list[float]:
        """Project into the canonical `FEATURE_ORDER` row the GBDT expects."""
        return [float(getattr(self, name)) for name in FEATURE_ORDER]

    def has_minimum_signal(self) -> bool:
        """True iff the cluster has enough early breadth/volume to trust the GBDT."""
        return self.e_posts >= _MIN_POSTS_FOR_MODEL and self.e_ch >= _MIN_CHANNELS_FOR_MODEL


@runtime_checkable
class ViralModel(Protocol):
    """A virality model: early features -> probability of eventual virality in [0, 1]."""

    def predict_proba(self, features: EarlyFeatures) -> float: ...


@dataclass(frozen=True)
class FormulaFallbackModel:
    """Cold-start fallback: the deterministic v2 formula, normalised into [0, 1].

    Reuses `scorer.score.compute_viral_score` (the single formula source) over a
    `ScoreInputs` built from the early features — `delta_channel_count` uses the
    breadth-minus-one convention of the formula's velocity term. The result is a
    monotone RANKING signal, not a calibrated probability (documented).
    """

    watched_channels_count: int = 1

    def __post_init__(self) -> None:
        if self.watched_channels_count < 1:
            raise ViralModelError(
                f"watched_channels_count must be >= 1, got {self.watched_channels_count}"
            )

    def predict_proba(self, features: EarlyFeatures) -> float:
        unique_channels = round(features.e_ch)
        # invert log1p(weighted_engagement) back to the raw weighted engagement the
        # formula expects; the formula re-applies its own log1p internally.
        weighted_engagement = math.expm1(features.e_eng_log)
        delta_hours = self._infer_delta_hours(features)
        inputs = ScoreInputs(
            views=round(weighted_engagement),
            forwards=0,
            reactions=0,
            channel_avg=1.0,
            delta_channel_count=max(unique_channels - 1, 0),
            delta_hours=delta_hours,
            unique_channels_count=unique_channels,
            watched_channels_count=self.watched_channels_count,
        )
        score = compute_viral_score(inputs)
        return min(max(score / _FORMULA_SCALE, 0.0), 1.0)

    @staticmethod
    def _infer_delta_hours(features: EarlyFeatures) -> float:
        """Recover an hours estimate from breadth velocity = log1p(channels)/hours.

        `e_burst` = breadth per hour ≈ channels / hours; invert to hours, clamped to a
        1-hour floor so a sub-hour burst cannot manufacture a tiny denominator.
        """
        if features.e_burst <= 0:
            return 1.0
        return max(features.e_ch / features.e_burst, 1.0)


class _Booster(Protocol):
    """The minimal LightGBM booster surface this module uses (keeps `Any` out)."""

    def predict(self, data: list[list[float]]) -> list[float]: ...


@dataclass(frozen=True)
class _LightGbmBoosterAdapter:
    """Confines lightgbm's ``Any``-typed `predict` to one boundary, returning floats.

    The wrapped object is the lightgbm `Booster`; its `predict` may return a numpy
    array / list / scalar, so the result is coerced into a concrete ``list[float]`` —
    nothing `Any`-typed escapes this adapter into the rest of the module.
    """

    _booster: object

    def predict(self, data: list[list[float]]) -> list[float]:
        predict_fn = getattr(self._booster, "predict", None)
        if not callable(predict_fn):
            raise ViralModelError("wrapped booster has no callable predict()")
        raw = predict_fn(data)
        return [float(value) for value in raw]


@dataclass(frozen=True)
class GbdtViralModel:
    """A loaded LightGBM virality model that emits a calibrated probability.

    Construct via `load` — it reads the booster's native text dump and the feature
    order it was trained on, and validates the feature order matches `FEATURE_ORDER`
    so a stale/re-ordered artifact is rejected loudly rather than mis-fed.
    """

    booster: _Booster
    feature_order: tuple[str, ...]

    def predict_proba(self, features: EarlyFeatures) -> float:
        if self.feature_order != FEATURE_ORDER:
            raise ViralModelError(
                f"model feature order {self.feature_order} != expected {FEATURE_ORDER}"
            )
        raw = self.booster.predict([features.as_vector()])
        if len(raw) != 1:
            raise ViralModelError(f"booster returned {len(raw)} predictions, expected 1")
        return min(max(float(raw[0]), 0.0), 1.0)

    @classmethod
    def load(cls, model_path: Path, *, feature_order: tuple[str, ...]) -> GbdtViralModel:
        """Load a LightGBM booster from its native text model file (no pickle).

        LightGBM is imported here, lazily — the backend does not depend on it unless a
        model is actually loaded. A missing file or a feature-order mismatch raises
        `ViralModelError` (fail fast, never silently mis-predict).
        """
        if feature_order != FEATURE_ORDER:
            raise ViralModelError(f"feature order {feature_order} != expected {FEATURE_ORDER}")
        if not model_path.exists():
            raise ViralModelError(f"model artifact not found: {model_path}")
        try:
            import lightgbm as lgb
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise ViralModelError("lightgbm is not installed; cannot load a GBDT model") from exc
        raw_booster = lgb.Booster(model_file=str(model_path))
        # Cross-check the feature names ACTUALLY baked into the artifact (not just the
        # caller-supplied tuple) so a renamed/reordered saved model is rejected rather
        # than silently mis-fed (closes code-review HIGH).
        artifact_features = tuple(str(name) for name in raw_booster.feature_name())
        if artifact_features != FEATURE_ORDER:
            raise ViralModelError(
                f"model artifact feature names {artifact_features} != required {FEATURE_ORDER}"
            )
        # Wrap the lightgbm Booster (whose `predict` signature is `Any`-typed) in a
        # tiny adapter that conforms to the strict `_Booster` Protocol — the `Any` is
        # confined to this boundary and the prediction is coerced to `list[float]`.
        return cls(
            booster=_LightGbmBoosterAdapter(raw_booster),
            feature_order=feature_order,
        )


class ModelChoice(Enum):
    """Which model produced a prediction (for logging / measuring the fallback split)."""

    GBDT = "gbdt"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Prediction:
    """A virality probability + which model produced it."""

    probability: float
    chosen: ModelChoice


def select_prediction(
    features: EarlyFeatures,
    *,
    gbdt: ViralModel | None,
    fallback: ViralModel,
) -> Prediction:
    """Use the GBDT when it is loaded AND the cluster clears the minimum-signal floor.

    Below the floor (cold-start singleton/pair) or when no GBDT is loaded, fall back to
    the formula. This is the policy the production scorer calls; it returns the chosen
    model so the caller can record the GBDT-vs-fallback ratio.
    """
    if gbdt is not None and features.has_minimum_signal():
        return Prediction(probability=gbdt.predict_proba(features), chosen=ModelChoice.GBDT)
    return Prediction(probability=fallback.predict_proba(features), chosen=ModelChoice.FALLBACK)
