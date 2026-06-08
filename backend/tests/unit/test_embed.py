"""AC3 — embed yields fixed-dim vectors; model is lazy (no torch import in unit).

The real sentence-transformers model is NEVER loaded here: tests inject a fake
`Encoder` (or monkeypatch `_get_model`). We also assert the heavy library is not
imported at module import time (lazy-load invariant, arch §7).
"""

import sys
from datetime import UTC, datetime

import pytest

from collector.base import PostMetrics, SourceKind, SourceRef
from pipeline.steps import embed
from pipeline.steps.normalize import NormalizedPost
from storage.models import EMBEDDING_DIM


class _FakeEncoder:
    """Deterministic encoder returning fixed-dim vectors; records that it ran."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        self.calls = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text))] * self._dim for text in texts]


def _post(text: str, external_id: str = "1") -> NormalizedPost:
    return NormalizedPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle="@chan"),
        external_id=external_id,
        text=text,
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def test_embed_returns_fixed_dim_vectors() -> None:
    encoder = _FakeEncoder()
    vectors = embed.run([_post("hello"), _post("world", "2")], encoder=encoder)
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    assert encoder.calls == 1


def test_embed_validates_dimension_mismatch() -> None:
    bad = _FakeEncoder(dim=EMBEDDING_DIM - 1)
    with pytest.raises(ValueError, match="dimension mismatch"):
        embed.run([_post("hi")], encoder=bad)


def test_embed_empty_input_no_model_load() -> None:
    # Empty input must NOT trigger the lazy model load (or any encoder call).
    assert embed.run([]) == []


def test_embed_model_is_lazy_not_loaded_at_import() -> None:
    # Importing the module must not import sentence_transformers / torch.
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules
    # The singleton starts unset; only populated on first `_get_model()`.
    assert embed._model is None


def test_embed_uses_get_model_when_no_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = _FakeEncoder()
    monkeypatch.setattr(embed, "_get_model", lambda: encoder)
    vectors = embed.run([_post("x")])
    assert len(vectors) == 1
    assert encoder.calls == 1


def test_get_model_caches_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = _FakeEncoder()
    load_calls = {"n": 0}

    def _fake_load() -> _FakeEncoder:
        load_calls["n"] += 1
        return encoder

    monkeypatch.setattr(embed, "_model", None)
    monkeypatch.setattr(embed, "_load_model", _fake_load)
    first = embed._get_model()
    second = embed._get_model()
    assert first is second is encoder
    assert load_calls["n"] == 1
