
from __future__ import annotations

import itertools
import random

import pytest

from src.core.config_bundle import constants as bundle_constants
from src.core.notifications import doc_model as M

DEST = "d_0123456789ab"
DEST2 = "d_ba9876543210"


def test_path_builders_and_parsers_round_trip() -> None:
    cases = [
        (M.dest_path(DEST), M.ParsedPath("dest", dest=DEST)),
        (M.tick_path("screen", "session.finished"), M.ParsedPath("tick", type_id="session.finished", col="screen")),
        (M.tick_path(DEST, "alert.account"), M.ParsedPath("tick", type_id="alert.account", col=DEST)),
        (M.tick_path("webpush:7", "session.died"), M.ParsedPath("tick", type_id="session.died", col="webpush:7")),
        (M.extra_path(DEST, "quiet"), M.ParsedPath("extra", dest=DEST, extra="quiet")),
        (M.default_path("session.died"), M.ParsedPath("default", type_id="session.died")),
        (M.local_key("paused"), M.ParsedPath("local", name="paused")),
    ]
    for path, parsed in cases:
        assert M.parse_path(path) == parsed, path
    assert [M.extra_path(DEST, e).rsplit("/", 1)[1] for e in M.EXTRAS] == ["away", "quiet", "reminder", "projects",
                                                                           "details"]


@pytest.mark.parametrize("bad", ["", "dest/", "dest/x", "tick/screen/nope", "tick/nope/session.died",
                                 f"extra/{DEST}/sing", "default/", "local/", "local/a/b", "weird/x", f"dest/{DEST}/x"])
def test_malformed_paths_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        M.parse_path(bad)


def test_builders_refuse_unregistered_parts() -> None:
    with pytest.raises(ValueError):
        M.tick_path("screen", "made.up")
    with pytest.raises(ValueError):
        M.dest_path("nope")
    with pytest.raises(ValueError):
        M.local_key("a/b")
    assert M.is_local_only("local/paused") and not M.is_local_only("dest/x")


def test_effective_value_local_wins_and_reset_returns_to_global() -> None:
    p = M.tick_path("screen", "session.finished")
    doc = M.set_global(M.empty_doc(), p, True, "a")
    assert M.effective_value(doc, p) is True and M.effective_source(doc, p) == "global" and not M.is_pinned(doc, p)
    pinned = M.set_local(doc, p, False)
    assert M.effective_value(pinned, p) is False and M.effective_source(pinned, p) == "local" and M.is_pinned(pinned, p)
    assert doc["local"] == {}
    reset = M.clear_local(pinned, p)
    assert M.effective_value(reset, p) is True and M.effective_source(reset, p) == "global"
    assert M.effective_value(M.empty_doc(), p, default="d") == "d" and M.effective_source(M.empty_doc(), p) == "absent"
    only = M.set_local(M.empty_doc(), M.local_key("paused"), True)
    assert M.effective_value(only, "local/paused") is True
    with pytest.raises(ValueError):
        M.set_global(M.empty_doc(), "local/paused", True, "a")


def test_lamport_compare_orders_by_counter_then_install_id() -> None:
    assert M.compare_versions((2, "a"), (1, "z")) == 1
    assert M.compare_versions((1, "z"), (2, "a")) == -1
    assert M.compare_versions((3, "a"), (3, "b")) == -1 and M.compare_versions((3, "b"), (3, "a")) == 1
    assert M.compare_versions((3, "a"), (3, "a")) == 0
    assert M.parse_version([4, "x"]) == (4, "x")
    for bad in (None, [1], [True, "a"], [-1, "a"], [1, ""], "ab"):
        with pytest.raises(ValueError):
            M.parse_version(bad)


def test_set_global_bumps_the_counter_past_a_tombstone() -> None:
    p = M.dest_path(DEST)
    doc = M.set_global(M.empty_doc(), p, {"kind": "slack"}, "a")
    assert doc["global"][p]["ver"] == [1, "a"]
    gone = M.delete_global(doc, p, "a", now=100.0)
    assert M.is_tombstone(gone["global"][p]) and gone["global"][p]["ver"] == [2, "a"]
    assert M.effective_source(gone, p) == "absent"
    back = M.set_global(gone, p, {"kind": "slack"}, "a")
    assert back["global"][p]["ver"] == [3, "a"] and M.effective_source(back, p) == "global"


def _random_map(rng: random.Random) -> dict:
    paths = [M.tick_path("screen", "session.finished"), M.tick_path(DEST, "alert.account"), M.dest_path(DEST),
             M.default_path("session.died")]
    out = {}
    for p in rng.sample(paths, rng.randint(0, len(paths))):
        ver = [rng.randint(1, 3), rng.choice("abc")]
        out[p] = ({"tomb": float(rng.randint(0, 9)), "ver": ver} if rng.random() < 0.3
                  else {"val": rng.choice([True, False, 1]), "ver": ver})
    return out


def test_merge_is_commutative_associative_and_idempotent() -> None:
    rng = random.Random(1278)
    maps = [_random_map(rng) for _ in range(40)]
    assert any(maps), "population check: the generator must produce entries"
    for a, b in itertools.combinations(maps, 2):
        assert M.merge_global(a, b) == M.merge_global(b, a)
    for a, b, c in zip(maps, maps[1:], maps[2:]):
        assert M.merge_global(M.merge_global(a, b), c) == M.merge_global(a, M.merge_global(b, c))
    for a in maps:
        assert M.merge_global(a, a) == a and M.merge_global(a, {}) == a


def test_merge_higher_version_wins_and_two_computers_converge() -> None:
    p = M.tick_path("screen", "session.finished")
    one = M.set_global(M.empty_doc(), p, True, "aaa")
    two = M.set_global(one, p, False, "bbb")
    assert M.merge_global(one["global"], two["global"])[p]["val"] is False
    x = M.set_global(M.empty_doc(), p, True, "aaa")["global"]
    y = M.set_global(M.empty_doc(), p, False, "bbb")["global"]
    assert M.merge_global(x, y) == M.merge_global(y, x) and M.merge_global(x, y)[p]["val"] is False


def test_tombstones_expire_after_30_days_and_live_entries_stay() -> None:
    p, q = M.dest_path(DEST), M.dest_path(DEST2)
    g = {p: {"tomb": 1000.0, "ver": [2, "a"]}, q: {"val": {}, "ver": [1, "a"]}}
    assert M.TOMBSTONE_TTL_SECONDS == 30 * 86400
    assert M.prune_tombstones(g, now=1000.0 + M.TOMBSTONE_TTL_SECONDS) == g
    assert M.prune_tombstones(g, now=1000.0 + M.TOMBSTONE_TTL_SECONDS + 1) == {q: g[q]}


def test_block_stays_out_of_the_config_bundle() -> None:
    assert M.BLOCK == "notification_routing"
    assert bundle_constants.EXPORTED_SECTIONS and "notifications" in bundle_constants.EXPORTED_SECTIONS
    assert M.BLOCK not in bundle_constants.EXPORTED_SECTIONS
