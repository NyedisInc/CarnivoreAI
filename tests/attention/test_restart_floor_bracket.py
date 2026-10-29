
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.attention.ledger import AttentionLedger
from src.core.attention.restart_floor import restart_bracket
from src.core.attention.watcher import AttentionWatcher

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _watcher() -> AttentionWatcher:
    return AttentionWatcher(
        list_targets=lambda: [], read_evidence=lambda _t, _n: None,
        raise_toast=lambda *_a: None, set_unread=lambda *_a: None,
        on_busy_edge=lambda *_a: None, ledger=AttentionLedger(),
        now=lambda: NOW, registry_directory="/nonexistent-registry-dir",
    )


def test_a_replacing_restart_keeps_its_floor_and_clears_the_restarting_mark():
    watcher, backend = _watcher(), SimpleNamespace()
    with restart_bracket(watcher, backend, "ses_1") as window:
        assert backend._attention_restarting is True
        assert watcher.process_floor_for("ses_1") == NOW
        window.replaced = True
    assert backend._attention_restarting is False
    assert backend._attention_generation == 1
    assert watcher.process_floor_for("ses_1") == NOW


def test_a_restart_that_replaced_nothing_takes_its_floor_back():
    watcher, backend = _watcher(), SimpleNamespace()
    with restart_bracket(watcher, backend, "ses_1"):
        pass
    assert watcher.process_floor_for("ses_1") is None


def test_a_respawn_that_raised_takes_its_floor_back():
    watcher, backend = _watcher(), SimpleNamespace(_attention_generation=4)
    with pytest.raises(RuntimeError):
        with restart_bracket(watcher, backend, "ses_1"):
            raise RuntimeError("tmux went away")
    assert watcher.process_floor_for("ses_1") is None
    assert backend._attention_restarting is False
    assert backend._attention_generation == 5
