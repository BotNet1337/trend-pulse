"""Embedding step (task-007 step 3, AC3) — lazy sentence-transformers model.

`run` turns `NormalizedPost`s into fixed-dimension float vectors. The heavy
sentence-transformers model (→ torch) is loaded LAZILY via a module-level
singleton on the first `run`/`_get_model()` call — NEVER at import — so importing
this module (and the `api` process) stays light (arch §7: ml stack only in the
worker). The model name comes from settings (`embedding_model_name`), and every
output vector is validated to be exactly `EMBEDDING_DIM` (storage single source of
truth) — fail-fast on dimension drift rather than silently corrupting pgvector.

Testability: `run` accepts an optional `encoder` (any `Encoder`), and `_get_model`
is monkeypatchable, so unit tests inject a fake encoder and never import torch.
Platform-independent: depends only on `NormalizedPost` (ADR-001).
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from config import get_settings
from pipeline.steps.normalize import NormalizedPost
from storage.models import EMBEDDING_DIM

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@runtime_checkable
class Encoder(Protocol):
    """Minimal encoder surface (matches sentence-transformers `SentenceTransformer`).

    Returns one vector (list of floats) per input text, in order.
    """

    def encode(self, texts: list[str]) -> list[list[float]]: ...


# Lazy process-wide model singleton — populated on first use, not at import.
_model: Encoder | None = None


def _load_model() -> Encoder:
    """Load the sentence-transformers model named in settings (heavy import).

    Imported INSIDE the function so `import pipeline.steps.embed` never pulls torch.
    """
    from sentence_transformers import SentenceTransformer

    model_name = get_settings().embedding_model_name
    return _SentenceTransformerEncoder(SentenceTransformer(model_name))


def _get_model() -> Encoder:
    """Return the cached encoder, loading it lazily on first call (singleton)."""
    global _model
    if _model is None:
        _model = _load_model()
    return _model


class _SentenceTransformerEncoder:
    """Adapt `SentenceTransformer` to the `Encoder` protocol (vectors as lists)."""

    def __init__(self, model: "SentenceTransformer") -> None:
        self._model = model

    def encode(self, texts: list[str]) -> list[list[float]]:
        # `SentenceTransformer.encode` returns an ndarray; normalize to lists so the
        # step output is plain JSON-friendly floats and the dtype never leaks out.
        raw = self._model.encode(texts)
        return [[float(value) for value in vector] for vector in raw]


def _validate_dim(vectors: list[list[float]]) -> None:
    """Fail fast if any vector is not exactly `EMBEDDING_DIM` (arch §7)."""
    for index, vector in enumerate(vectors):
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding dimension mismatch at index {index}: "
                f"got {len(vector)}, expected {EMBEDDING_DIM}"
            )


def run(posts: list[NormalizedPost], encoder: Encoder | None = None) -> list[list[float]]:
    """Embed each post's text into a fixed-dim vector (one per post, in order).

    `encoder` defaults to the lazily-loaded singleton model; tests inject a fake.
    Empty input → empty list (no model load forced). Output dims are validated.
    """
    if not posts:
        return []
    model = encoder if encoder is not None else _get_model()
    vectors = model.encode([post.text for post in posts])
    _validate_dim(vectors)
    return vectors
