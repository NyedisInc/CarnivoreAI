
from __future__ import annotations

import random

from src.core.notifications import doc_model, types

DESTS = ["d_" + f"{i:012x}" for i in range(1, 4)]
INSTALLS = ["n_a", "n_b", "n_c"]


def random_map(rng: random.Random) -> dict:
    out = {}
    paths = [doc_model.dest_path(d) for d in DESTS] + [doc_model.default_path(t.id) for t in types.ordered_types()[:5]]
    paths += [doc_model.tick_path(DESTS[0], types.ordered_types()[0].id)]
    for path in paths:
        if rng.random() < 0.3:
            continue
        ver = [rng.randint(1, 3), rng.choice(INSTALLS)]
        if rng.random() < 0.3:
            out[path] = {"tomb": float(rng.randint(1, 9)), "ver": ver}
        else:
            out[path] = {"val": rng.choice([True, False, {"name": "x"}, {"name": "y"}]), "ver": ver}
    return out


def test_merge_is_commutative_associative_and_idempotent():
    rng = random.Random(1278)
    seen_tombstone = seen_tie = False
    for _ in range(300):
        a, b, c = random_map(rng), random_map(rng), random_map(rng)
        merge = doc_model.merge_global
        assert merge(a, b) == merge(b, a)
        assert merge(merge(a, b), c) == merge(a, merge(b, c))
        assert merge(a, a) == a
        assert merge(merge(a, b), b) == merge(a, b)
        seen_tombstone |= any("tomb" in e for e in a.values())
        seen_tie |= any(p in b and a[p]["ver"] == b[p]["ver"] for p in a)
    assert seen_tombstone and seen_tie, "the generator must exercise tombstones and equal versions"


def test_a_tie_on_the_counter_is_broken_by_install_id():
    low = {"p": {"val": 1, "ver": [4, "n_a"]}}
    high = {"p": {"val": 2, "ver": [4, "n_b"]}}
    assert doc_model.merge_global(low, high) == doc_model.merge_global(high, low) == high
