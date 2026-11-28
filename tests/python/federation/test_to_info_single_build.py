
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "perf"))
import mesh_cost_roles  # noqa: E402

from src.core.federation import peer_listing, shadow_rows  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402

PEER = SimpleNamespace(key="peer-ab12", label="studio", peer_install_id="iid-x")
SHADOW = shadow_rows.Shadow(7, 3, "proj")


def fuzzed_rows() -> list:
    rows = mesh_cost_roles.build_rows("iid-x", 20)
    rng, out = random.Random(5), list(rows)
    for row in rows:
        r = copy.deepcopy(row)
        for key in rng.sample(sorted(r), 6):
            if key not in ("session", "tmux_session", "session_uuid"):
                r.pop(key)
        out.append(r)
        r = copy.deepcopy(row)
        r["unknown_extra"], r["session"]["extra"] = {"a": 1}, 2
        r["tmux_session"] = rng.choice(["carnivore_x y", "cloude_é", "", None, "a" * 80])
        r["label"] = None
        out.append(r)
    for field, value in (("pty_pid", 123), ("pty_pid", None), ("pty_pid", "9"), ("pty_pid", True)):
        r = copy.deepcopy(rows[0])
        r["session"][field] = value
        out.append(r)
    for field, value in (("project_id", 9), ("project_id", "x"), ("host_state", 5), ("session_row_id", "4"), ("parent_session_id", "p"), ("project_name", 3), ("host_key", None)):
        r = copy.deepcopy(rows[1])
        r[field] = value
        out.append(r)
    r = copy.deepcopy(rows[2])
    r["session"]["id"] = 5
    out.append(r)
    out.append({**rows[3], "session": "not a mapping"})
    out.append({k: v for k, v in rows[4].items() if k != "session"})
    return out


def build(raw: dict, on: bool, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
    try:
        return peer_listing.to_info(copy.deepcopy(raw), SHADOW, PEER)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, str(exc)


def same(a, b) -> bool:
    if isinstance(a, tuple) or isinstance(b, tuple):
        return a == b
    return (a.model_dump(mode="json") == b.model_dump(mode="json") and a.model_fields_set == b.model_fields_set
            and a.session.model_fields_set == b.session.model_fields_set)


def test_the_single_build_equals_the_old_build_for_every_row(monkeypatch):
    rows = fuzzed_rows()
    for raw in rows:
        old, new = build(raw, False, monkeypatch), build(raw, True, monkeypatch)
        assert same(old, new), (raw.get("tmux_session"), old, new)
    assert sum(1 for raw in rows if not isinstance(build(raw, False, monkeypatch), tuple)) > 40


def test_a_single_build_that_keeps_the_raw_pty_pid_turns_the_differential_red(monkeypatch):
    real = peer_listing._to_info_single

    def keeps_pty_pid(raw, shadow, peer):
        info = real(raw, shadow, peer)
        info.session.pty_pid = raw["session"].get("pty_pid")
        return info

    monkeypatch.setattr(peer_listing, "_to_info_single", keeps_pty_pid)
    raw = copy.deepcopy(mesh_cost_roles.build_rows("iid-x", 1)[0])
    raw["session"]["pty_pid"] = 123
    assert not same(build(raw, False, monkeypatch), build(raw, True, monkeypatch))
