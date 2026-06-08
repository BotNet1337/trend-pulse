"""AC7 — pipeline steps are platform-independent (no Telegram coupling).

Two checks: (1) the steps run on a generic `RawPost` regardless of `source.kind`;
(2) no step module imports anything from `collector.telegram` (static, via the
module source + the import graph).
"""

import ast
import inspect
from datetime import UTC, datetime
from types import ModuleType

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from pipeline.steps import cluster, dedup, embed, normalize
from storage.models import EMBEDDING_DIM

_STEP_MODULES = [dedup, normalize, embed, cluster]


class _FakeEncoder:
    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


def _imported_modules(module: ModuleType) -> set[str]:
    """Collect dotted module names referenced by `import`/`from` in a module."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_step_imports_collector_telegram() -> None:
    for module in _STEP_MODULES:
        for imported in _imported_modules(module):
            assert not imported.startswith("collector.telegram"), (
                f"{module.__name__} must not import {imported} (AC7)"
            )


def test_steps_run_on_generic_rawpost() -> None:
    # A non-Telegram source kind flows through the whole pure chain.
    post = RawPost(
        source=SourceRef(kind=SourceKind.TWITTER, handle="generic"),
        external_id="1",
        author="a",
        text="some generic platform-independent content here",
        media_hashes=(),
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )
    deduped = dedup.run([post])
    normalized = normalize.run(deduped)
    vectors = embed.run(normalized, encoder=_FakeEncoder())
    candidates = cluster.run(normalized, vectors)
    assert len(candidates) == 1
    assert candidates[0].handles == ("generic",)
