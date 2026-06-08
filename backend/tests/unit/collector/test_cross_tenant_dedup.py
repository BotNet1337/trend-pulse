"""AC5 — cross-tenant dedup: shared channel appears exactly once in the read union."""

from collector.base import SourceKind, SourceRef
from collector.telegram.dedup import normalize_handle, unique_refs


def test_two_watchlists_sharing_a_channel_dedup_to_one_ref() -> None:
    # Two tenants' watchlists, both watching @news (plus distinct channels).
    tenant_a = [
        SourceRef(SourceKind.TELEGRAM, "@news"),
        SourceRef(SourceKind.TELEGRAM, "@alpha"),
    ]
    tenant_b = [
        SourceRef(SourceKind.TELEGRAM, "@news"),
        SourceRef(SourceKind.TELEGRAM, "@beta"),
    ]
    union = unique_refs(tenant_a + tenant_b)
    handles = [r.handle for r in union]

    assert handles.count("@news") == 1
    assert set(handles) == {"@news", "@alpha", "@beta"}


def test_case_and_url_prefix_normalize_to_one_ref() -> None:
    refs = [
        SourceRef(SourceKind.TELEGRAM, "@Channel"),
        SourceRef(SourceKind.TELEGRAM, "@channel"),
        SourceRef(SourceKind.TELEGRAM, "https://t.me/channel"),
        SourceRef(SourceKind.TELEGRAM, "t.me/CHANNEL"),
    ]
    union = unique_refs(refs)

    assert len(union) == 1
    assert union[0].handle == "@channel"


def test_normalize_handle_forms() -> None:
    assert normalize_handle("@FooBar", SourceKind.TELEGRAM) == "@foobar"
    assert normalize_handle("https://t.me/FooBar", SourceKind.TELEGRAM) == "@foobar"
    assert normalize_handle("foobar", SourceKind.TELEGRAM) == "@foobar"


def test_union_preserves_first_seen_order() -> None:
    refs = [
        SourceRef(SourceKind.TELEGRAM, "@c"),
        SourceRef(SourceKind.TELEGRAM, "@a"),
        SourceRef(SourceKind.TELEGRAM, "@c"),
        SourceRef(SourceKind.TELEGRAM, "@b"),
    ]
    assert [r.handle for r in unique_refs(refs)] == ["@c", "@a", "@b"]
