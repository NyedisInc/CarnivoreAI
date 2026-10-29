
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.tmux_listing import TmuxListing
from src.core.tmux_socket_resolution import (
    CACHE_ATTR,
    configured_tmux_socket_name,
    resolve_probe_socket,
)


class _Manager:
    pass


def _listing(*names: str, ok: bool = True) -> TmuxListing:
    if not ok:
        return TmuxListing.unavailable("timeout")
    return TmuxListing.answered([{"name": n} for n in names])


def _calls_recorder():
    calls: list = []

    def make(answers: dict):
        def list_for_socket(candidate: str):
            calls.append(candidate)
            if candidate in answers:
                return answers[candidate]
            return candidate, _listing()

        return list_for_socket

    return calls, make




def test_explicit_config_wins_verbatim_and_probes_only_once():
    mgr = _Manager()
    calls, make = _calls_recorder()
    winning = _listing("some_session")
    list_for_socket = make({"my-custom-socket": ("my-custom-socket", winning)})

    socket_name, listing = resolve_probe_socket(mgr, "my-custom-socket", list_for_socket)

    assert socket_name == "my-custom-socket"
    assert listing is winning
    assert calls == ["my-custom-socket"], (
        "an explicit config value is a single candidate - it must never "
        "also be checked against the legacy ladder"
    )
    assert getattr(mgr, CACHE_ATTR, None) is None, (
        "the explicit-config path is re-read live every call and must "
        "never populate the unconfigured-case cache"
    )


def test_explicit_config_is_reread_live_not_cached():
    mgr = _Manager()
    calls, make = _calls_recorder()
    list_for_socket = make({
        "socket-a": ("socket-a", _listing("s1")),
        "socket-b": ("socket-b", _listing("s2")),
    })

    first = resolve_probe_socket(mgr, "socket-a", list_for_socket)
    second = resolve_probe_socket(mgr, "socket-b", list_for_socket)

    assert first[0] == "socket-a"
    assert second[0] == "socket-b"
    assert calls == ["socket-a", "socket-b"]




def test_no_config_falls_through_to_a_legacy_socket_that_has_sessions():
    from structlog.testing import capture_logs

    mgr = _Manager()
    calls, make = _calls_recorder()
    legacy_listing = _listing("cloude_a", "cloude_b")
    list_for_socket = make({
        "carnivore": ("carnivore", _listing()),
        "cloude": ("cloude", legacy_listing),
    })

    with capture_logs() as logs:
        socket_name, listing = resolve_probe_socket(mgr, None, list_for_socket)

    assert socket_name == "cloude"
    assert listing is legacy_listing
    assert calls == ["carnivore", "cloude"], (
        "current name tried first, legacy name tried only because the "
        "current one had nothing"
    )
    assert getattr(mgr, CACHE_ATTR, None) == "cloude"
    adopted = [e for e in logs if e["event"] == "legacy_tmux_socket_adopted"]
    assert len(adopted) == 1, (
        "rung (3) of the phase-4 plan requires this logged exactly once"
    )
    assert adopted[0]["socket"] == "cloude"
    assert adopted[0]["current_socket"] == "carnivore"

    with capture_logs() as logs_again:
        resolve_probe_socket(mgr, None, list_for_socket)
    assert not [
        e for e in logs_again if e["event"] == "legacy_tmux_socket_adopted"
    ], "a cache hit must not re-log the adoption"


def test_the_winning_socket_is_cached_for_the_rest_of_the_process():
    mgr = _Manager()
    calls, make = _calls_recorder()
    legacy_listing_1 = _listing("cloude_a")
    legacy_listing_2 = _listing("cloude_a", "cloude_new")
    list_for_socket = make({
        "carnivore": ("carnivore", _listing()),
        "cloude": ("cloude", legacy_listing_1),
    })

    first = resolve_probe_socket(mgr, None, list_for_socket)
    assert first == ("cloude", legacy_listing_1)
    assert calls == ["carnivore", "cloude"]

    calls.clear()
    list_for_socket_2 = make({"cloude": ("cloude", legacy_listing_2)})
    calls2, make2 = _calls_recorder()
    lfs2 = make2({"cloude": ("cloude", legacy_listing_2)})
    second = resolve_probe_socket(mgr, None, lfs2)

    assert second == ("cloude", legacy_listing_2), "listing is re-taken, not cached"
    assert calls2 == ["cloude"], "cached resolution skips re-walking the ladder"




def test_no_config_and_nothing_found_anywhere_defaults_to_the_current_name():
    mgr = _Manager()
    calls, make = _calls_recorder()
    empty_current = _listing()
    list_for_socket = make({
        "carnivore": ("carnivore", empty_current),
        "cloude": ("cloude", _listing()),
    })

    socket_name, listing = resolve_probe_socket(mgr, None, list_for_socket)

    assert socket_name == "carnivore", "a fresh install must never settle on a legacy name"
    assert listing is empty_current
    assert calls == ["carnivore", "cloude"]
    assert getattr(mgr, CACHE_ATTR, None) == "carnivore"


def test_no_config_and_every_candidate_unavailable_still_defaults_to_current():
    mgr = _Manager()
    calls, make = _calls_recorder()
    unavailable = _listing(ok=False)
    list_for_socket = make({
        "carnivore": ("carnivore", unavailable),
        "cloude": ("cloude", _listing(ok=False)),
    })

    socket_name, listing = resolve_probe_socket(mgr, None, list_for_socket)

    assert socket_name == "carnivore"
    assert listing is unavailable
    assert listing.ok is False




def test_the_actual_bound_socket_wins_over_the_requested_candidate():
    mgr = _Manager()
    pinned_listing = _listing("pinned_session")

    def list_for_socket(candidate: str):
        return "harness-pinned-socket", pinned_listing

    socket_name, listing = resolve_probe_socket(mgr, None, list_for_socket)

    assert socket_name == "harness-pinned-socket"
    assert listing is pinned_listing
    assert getattr(mgr, CACHE_ATTR, None) == "harness-pinned-socket"


def test_a_manager_that_refuses_setattr_still_resolves_correctly():

    class Stubborn:
        def __setattr__(self, name, value):
            raise RuntimeError("no attributes for you")

    mgr = Stubborn()
    _, make = _calls_recorder()
    list_for_socket = make({"cloude": ("cloude", _listing("s1"))})

    socket_name, listing = resolve_probe_socket(mgr, None, list_for_socket)
    assert socket_name == "cloude"




class _SettingsStub:
    def __init__(self, auth_config_file):
        self.auth_config_file = str(auth_config_file)


def test_configured_socket_name_is_none_when_config_json_has_no_session_block(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {}}))

    result = configured_tmux_socket_name(_SettingsStub(config_path))

    assert result is None, (
        "a config.json that never mentions session.tmux_socket_name must "
        "read back as None, never as the pydantic schema default"
    )


def test_configured_socket_name_is_none_when_session_block_has_no_key(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"session": {"backend": "tmux"}}))

    assert configured_tmux_socket_name(_SettingsStub(config_path)) is None


def test_configured_socket_name_reads_an_explicit_value(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"session": {"tmux_socket_name": "cloude"}}))

    assert configured_tmux_socket_name(_SettingsStub(config_path)) == "cloude"


def test_configured_socket_name_is_none_when_config_json_is_missing(tmp_path):
    missing = tmp_path / "does-not-exist.json"

    assert configured_tmux_socket_name(_SettingsStub(missing)) is None


def test_configured_socket_name_is_none_when_config_json_is_unparsable(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{not valid json")

    assert configured_tmux_socket_name(_SettingsStub(config_path)) is None


def test_configured_socket_name_parses_once_and_sees_a_replaced_file(tmp_path, monkeypatch):
    import os

    from src.config import config_file

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"session": {"tmux_socket_name": "first"}}))
    parses = []
    real = config_file.read_config
    monkeypatch.setattr(config_file, "read_config", lambda p: parses.append(p) or real(p))
    stub = _SettingsStub(config_path)

    assert configured_tmux_socket_name(stub) == "first"
    assert configured_tmux_socket_name(stub) == "first"
    assert len(parses) == 1

    staged = tmp_path / "config.json.tmp"
    staged.write_text(json.dumps({"session": {"tmux_socket_name": "second"}}))
    os.replace(staged, config_path)
    assert configured_tmux_socket_name(stub) == "second"
    assert len(parses) == 2
