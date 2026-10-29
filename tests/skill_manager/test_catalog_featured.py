
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

from src.api.catalog_views import item_view
from src.core.catalog.index_cache import IndexSnapshot
from src.core.catalog.index_snapshot import content_fingerprint
from src.core.catalog.minisign import parse_public_key
from src.core.catalog.trust_root import TrustRoot
from src.core.catalog.verify import verify_index
from src.core.catalog.verify_types import VerifiedIndex
from src.core.mcp import tools
from tests.helpers.catalog_fixture import DEFAULT_GENERATED_AT, build_signed_index, seal, skill_item
from tests.helpers.minisign_keys import generate_keypair, require_minisign

NOW = DEFAULT_GENERATED_AT + timedelta(days=1)


def _verify(tmp_path, featured, newer_first: bool = False) -> VerifiedIndex:
    require_minisign()
    (tmp_path / "i").mkdir(parents=True, exist_ok=True)
    (tmp_path / "p").mkdir(parents=True, exist_ok=True)
    index_kp = generate_keypair(tmp_path / "i")
    pub_kp = generate_keypair(tmp_path / "p")
    items = [skill_item(n, "alex", "ab" * 32) for n in ("a", "b", "c")]
    old = items[0]["versions"][0]
    newer = copy.deepcopy(old)
    newer["v"] = "2.0.0"
    newer["published_at"] = "2026-10-01T00:00:00+00:00"
    items[0]["versions"] = [newer, old] if newer_first else [old, newer]
    signed = build_signed_index(tmp_path, index_keypair=index_kp, publisher_keypair=pub_kp, items=items)
    if featured is not None:
        doc: dict[str, Any] = copy.deepcopy(signed.document)
        doc["featured"] = featured
        signed = seal(tmp_path, doc, index_kp)
    root = TrustRoot(index_key=parse_public_key(index_kp.public_key_text), publisher_key=parse_public_key(pub_kp.public_key_text))
    result = verify_index(
        signed.index_bytes, signed.minisig_text, trust_root=root, seen_revocations=frozenset(),
        last_verified_serial=0, now=NOW, consented_serial=None,
    )
    assert isinstance(result, VerifiedIndex), result
    return result


def _snap(v: VerifiedIndex) -> IndexSnapshot:
    return IndexSnapshot(verified=v, refusal=None, as_of=None, degraded=False, fetched_at=None, stale=False)


def test_featured_rank_first_published_fingerprint_and_tool(tmp_path):
    v = _verify(tmp_path, ["alex/b", "alex/a"])
    assert v.featured == ("alex/b", "alex/a")
    snap = _snap(v)
    views = {i.id: item_view(i, installed=None, snapshot=snap, untrusted=False) for i in v.items}
    assert (views["alex/b"].featured_rank, views["alex/a"].featured_rank, views["alex/c"].featured_rank) == (0, 1, None)
    assert views["alex/a"].first_published_at == "2026-09-01T12:00:00+00:00"
    v2 = _verify(tmp_path / "x", ["alex/b", "alex/a"], newer_first=True)
    assert item_view(v2.items[0], installed=None, snapshot=_snap(v2), untrusted=False).first_published_at == "2026-09-01T12:00:00+00:00"

    none = _verify(tmp_path / "n", None)
    assert none.featured == ()
    assert all(
        item_view(i, installed=None, snapshot=_snap(none), untrusted=False).featured_rank is None for i in none.items
    )

    assert "catalog_items_list" in tools._TOOLS
    assert "catalog_items_list" not in tools.WRITE_TOOLS


def test_fingerprint_moves_when_only_featured_changes():
    base = _verify_stub(())
    assert content_fingerprint(_snap(base)) != content_fingerprint(_snap(_verify_stub(("alex/a",))))


def _verify_stub(featured):
    from datetime import timezone
    return VerifiedIndex(
        serial=1, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc), degraded=False, items=(), untrusted_items=(),
        refused=(), revocations=(), index_key_id="x", featured=featured,
    )
