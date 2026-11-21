
from __future__ import annotations

import functools
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from src.core.app_alerts import kinds, service
from src.core.codex_helpers import constants as K
from src.core.codex_helpers import runtime
from src.core.codex_helpers.check import HelperCheck, run_check
from src.core.codex_helpers.handshake import probe_host
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.notifications import types as notify_types
from tests.python.codex_helpers import fakes

FAST = functools.partial(probe_host, timeout=1.5)


@pytest.fixture()
def world(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    raised: List[dict] = []
    service.configure(db, None)
    service.on_raised(raised.append)
    changes: List[int] = []
    codex = fakes.make_install(tmp_path / "install", host="hangs")
    checks: List[HelperCheck] = []

    def checker(identity, version):
        check = run_check(identity, version, prober=FAST)
        checks.append(check)
        return check

    runtime.install(lambda: str(codex), lambda _b: "0.170.0", checker=checker, on_change=lambda: changes.append(1))
    yield SimpleNamespace(db=db, raised=raised, changes=changes, codex=codex, checks=checks)
    runtime.uninstall()
    service.configure(None, None)


def _open_alerts(world) -> List[dict]:
    return [a for a in service.list_view(world.db, include_closed=False, limit=50)["alerts"]
            if a["key"].startswith(K.ALERT_KEY_PREFIX)]


@fakes.needs_xattr
def test_blocked_raises_one_alert_and_one_notification_then_a_pass_resolves_it(world):
    fakes.quarantine(world.codex.parent / K.HOST_NAME, fakes.UNAPPROVED)
    first = runtime.check_now()
    assert first.verdict == K.BLOCKED
    alerts = _open_alerts(world)
    assert [a["key"] for a in alerts] == ["self_check.codex_helpers.0.170.0"]
    assert alerts[0]["kind"] == "needs_you"
    assert [a["id"] for a in alerts[0]["actions"]] == ["open_security", "recheck"]
    assert len(world.raised) == 1 and world.changes == [1]

    again = runtime.check_now()
    assert again.verdict == K.BLOCKED and len(world.checks) == 2
    assert len(world.raised) == 1 and len(_open_alerts(world)) == 1 and world.changes == [1]

    fakes.set_host(world.codex, "answers")
    fixed = runtime.check_now()
    assert fixed.verdict == K.OK
    assert _open_alerts(world) == [] and world.changes == [1, 1]
    assert runtime.status()["check"]["verdict"] == K.OK and runtime.status()["check"]["text"] is None


@fakes.needs_xattr
def test_a_passing_install_is_cached_until_its_identity_changes(world):
    fakes.set_host(world.codex, "answers")
    assert runtime.check_now().verdict == K.OK
    assert runtime.check_now().verdict == K.OK and len(world.checks) == 1
    assert runtime.before_launch().verdict == K.OK and len(world.checks) == 1
    world.codex.write_text(world.codex.read_text() + "\n# a new version\n")
    assert runtime.check_now().verdict == K.OK and len(world.checks) == 2


def test_disarmed_hooks_spawn_nothing():
    runtime.uninstall()
    assert runtime.check_now() is None and runtime.before_launch() is None
    assert runtime.status() == {"armed": False, "check": None}


def test_the_alert_rides_the_phone_seeded_type_and_supports_recheck():
    key = K.ALERT_KEY_PREFIX + "0.170.0"
    assert notify_types.type_for_alert_key(key) == "alert.self_check"
    assert notify_types.get_type("alert.self_check").defaults.seed
    assert key.startswith(kinds.RECHECK_PREFIXES) and "privacy_security" in kinds.SYSTEM_PANES
