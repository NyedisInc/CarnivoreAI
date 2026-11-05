
from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict

import pytest
import pytest_asyncio

from src.core.attention.evidence import REASON_PERMISSION, REASON_QUESTION, REASON_TURN_ENDED
from src.core.notifications import types
from src.core.notifications.sources import toast as toast_source
from src.models import ToastNewMessage
from tests.python.notifications.emit.rig import SESSION, EmitRig

pytestmark = pytest.mark.asyncio

TOAST, BELL, FRAME, INBOX, NONE = "toast", "bell", "frame", "inbox", "none"


@dataclass(frozen=True)
class Row:

    type_id: str
    group: str
    screen: str
    fire: Callable[[EmitRig, Any], Awaitable[None]]
    outside: bool = True




def _attention(kind: str, reason: Any) -> Callable[[EmitRig, Any], Awaitable[None]]:
    async def fire(rig: EmitRig, _mp: Any) -> None:
        rig.manager.record_toast(session_id=SESSION, kind=kind, title="t", body=None,
                                 notify_type=toast_source.attention_notify_type(kind, reason))
    return fire


async def _terminal_notice(rig: EmitRig, _mp: Any) -> None:
    from src.core.session_output.escape_notices import TerminalNotices

    notices = TerminalNotices()
    notices._manager, notices._app_state, notices._send = rig.manager, rig.app_state, lambda *_a: None
    notices.on_output(SESSION, b"\x1b]9;build finished\x07")
    await rig.settle()


async def _agent_message(rig: EmitRig, mp: Any) -> None:
    from src.core.notifications import agent_message

    mp.setattr(agent_message, "enabled", lambda: True)
    await agent_message.send(rig.manager, SESSION, "deploy is green")


async def _plugin_notice(rig: EmitRig, _mp: Any) -> None:
    from src.cplugs.host.capabilities import toaster

    assert toaster("huddle", rig.app_state)(SESSION, "a question waits") is not None


async def _skill_tripwire(rig: EmitRig, _mp: Any) -> None:
    from src.core.skill_watch.tripwire import TripwireFinding
    from src.core.skill_watch.wiring import make_notice_raiser

    make_notice_raiser(rig.manager, rig.app_state, lambda *_a: None)(
        SimpleNamespace(session_id=SESSION), [TripwireFinding(skill="deploy", category="network")])


async def _died(rig: EmitRig, _mp: Any) -> None:
    from src.core.attention.evidence import REASON_PANE_DEAD
    from src.core.notifications.sources.died import DEAD_READS, DiedTracker

    tracker = DiedTracker(rig.manager, rig.app_state)
    target = SimpleNamespace(session_id=SESSION, key="k1", generation=1)
    observation = SimpleNamespace(verdict=SimpleNamespace(reason=REASON_PANE_DEAD))
    assert [tracker.observe(target, observation) for _ in range(DEAD_READS)][-1] is True


async def _auto_slept(rig: EmitRig, _mp: Any) -> None:
    from src.core.auto_sleep.sleeper import AutoSleeper

    async def info(_sid: str) -> Any:
        return SimpleNamespace(label="API", tmux_session="cloude_api", project_name="api")

    async def sleep(_uuid: str) -> Any:
        return SimpleNamespace(status="asleep", session_name="API")

    state = SimpleNamespace(session_manager=SimpleNamespace(get_session_info=info))
    sleeper = AutoSleeper(state, SimpleNamespace(forget=lambda _sid: None), sleep=sleep)
    assert await sleeper._act("ses_slept", "uuid-slept", 30) is True


async def _agent_update(rig: EmitRig, mp: Any) -> None:
    from src.core.notifications.sources import agent_update

    mp.setattr(agent_update, "stale_installed_version", lambda _w: "9.9.9")
    assert agent_update.check_once(None, rig.tmp) is True


async def _account_switched(rig: EmitRig, _mp: Any) -> None:
    from src.core.account_switch.auto_switch import record_switch

    record_switch(rig.app_state, provider="claude", from_account_id="max-1", to_account_id="max-2", reason="auto")


async def _restore(rig: EmitRig, mp: Any) -> None:
    from src.core.notifications.sources import restore

    mp.setattr(restore, "_announced", False)
    assert restore.on_offered("o_1") is True


async def _beast(rig: EmitRig, mp: Any) -> None:
    from src.core.beast_prompts import wiring

    mp.setattr(wiring.pending, "get_store", lambda: SimpleNamespace(record_beast=lambda **_k: None))
    mp.setattr(wiring, "summarize", lambda _d: ("Bash", "ls"))
    mp.setattr(wiring, "summary_line", lambda _d: "Bash: ls")
    info = SimpleNamespace(session=SimpleNamespace(id=SESSION), tmux_session="cloude_api")
    wiring.record_and_announce(lambda: rig.manager)(info, SimpleNamespace(kind="permission", fingerprint="f" * 32))


async def _auto_accepted(rig: EmitRig, mp: Any) -> None:
    from src.core.approvals.auto_answer import record

    mp.setattr(record.pending, "get_store", lambda: SimpleNamespace(record_beast=lambda **_k: None))
    info = SimpleNamespace(session=SimpleNamespace(id=SESSION), tmux_session="cloude_api")
    dialog = SimpleNamespace(kind="startup", startup_kind="folder_trust", fingerprint="f" * 32)
    record.record_and_announce(lambda: rig.manager)(info, dialog, "folder_trust", "Yes, I trust this folder", "project")


def _swarm(ref: str) -> Callable[[EmitRig, Any], Awaitable[None]]:
    async def fire(rig: EmitRig, mp: Any) -> None:
        from src.core.swarm import alerts

        mp.setattr(alerts, "_agent_for_thread", lambda _k: {"id": 3, "name": "builder", "body_session_uuid": None})
        mp.setattr(alerts.swarm_settings, "read_current",
                   lambda: SimpleNamespace(flash_per_agent_per_hour=99, flash_per_swarm_per_hour=99))
        alerts.LIMITS.reset()
        alerts.announce("agent:3", ref)
    return fire


async def _question_climbed(rig: EmitRig, _mp: Any) -> None:
    from src.core.swarm.cards import phone

    assert await phone.question_climbed(rig.app_state, 41, 7, "which key signs the build?") is True


def _alert(key: str, title_key: str) -> Callable[[EmitRig, Any], Awaitable[None]]:
    async def fire(rig: EmitRig, _mp: Any) -> None:
        from src.core.app_alerts import service

        assert service.raise_alert(key, source="emit_test", severity="warn", title_key=title_key) is not None
    return fire


async def _plugin_runtime(rig: EmitRig, _mp: Any) -> None:
    from src.core.app_alerts import service
    from src.cplugs.host.sidecar_boot import SidecarRuntime

    host = SimpleNamespace(_alert_writer=lambda: service.raise_alert, _publish_cplugs_later=lambda: None)
    SidecarRuntime._supervisor_alert(host, "mcphealth", "crash_loop", "3 crashes in 60 s")


async def _destination_disabled(rig: EmitRig, _mp: Any) -> None:
    from src.core.app_alerts import service

    assert service.raise_alert("notifications.destination_disabled", source="notifications", severity="warn",
                               title_key="app_alert.notifications.destination_disabled.title") is not None


async def _automation(rig: EmitRig, _mp: Any, which: str) -> None:
    from src.core.automations import notify_policy
    from src.core.automations.targets import recipe

    automation = {"name": "nightly", "delivery": {"notify": True, "notify_on": None}}
    if which == "report":
        notify_policy.tell(notify_policy.REPORT_TYPE, automation, "run_r")
    elif which == "failed":
        assert notify_policy.tell_alerted(automation, "run_f", 2) is True
    else:
        assert recipe.tell_notice("backups done") is True


async def _needs_login(rig: EmitRig, _mp: Any) -> None:
    from src.core.notifications.sources.login import LoginWatch

    def row(state: str) -> Any:
        return SimpleNamespace(id="max-1", name="max-1", provider="claude", credential_state=state, poke=None)

    watch = LoginWatch()
    watch.observe([row("live")])
    assert watch.observe([row("needs_login")]) == ["max-1"]


async def _wrong_code(rig: EmitRig, _mp: Any) -> None:
    from src.core.notifications.sources import computers

    assert computers.wrong_code("burned", "192.168.1.9") is True


async def _knock(rig: EmitRig, _mp: Any) -> None:
    from src.core.notifications.sources import computers

    assert computers.knock("Alex's laptop", "192.168.1.9", "ab12cd34") is True


async def _link_cert(rig: EmitRig, _mp: Any) -> None:
    from src.core.notifications.sources import computers

    assert computers.link_cert("rekeyed", "ab" * 32) is True


async def _update(rig: EmitRig, _mp: Any) -> None:
    from src.core.notifications.sources import update

    assert update.on_available("9.9.9", rig.tmp) is True


async def _stats_tripwire(rig: EmitRig, mp: Any) -> None:
    from src.core import session_change_notice
    from src.core.stats import config, tripwires
    from src.core.stats.store import StatsStore
    from src.models.stats import TripwireWrite

    store = StatsStore(rig.tmp / "stats")
    store.initialize()
    config.ensure_schema(store)
    tripwires.create_tripwire(store, TripwireWrite(name="errors", query={"metric": "total_tokens"}, comparator=">", threshold=1))
    mp.setattr(tripwires, "_measure", lambda *_a: 5.0)
    for frame in tripwires.evaluate_all(store):
        session_change_notice.publish(rig.app_state, frame)


async def _shape(rig: EmitRig, _mp: Any) -> None:
    import asyncio

    from src.core import shape_alert_wiring
    from src.core.subagents import shape_alert

    assert shape_alert_wiring.install(rig.app_state, asyncio.get_running_loop(), enabled=True) is True
    try:
        shape_alert._listener({"file_kind": "pid_registry", "contract_version": 1, "problems": ["status absent"]})
        await rig.settle()
    finally:
        shape_alert.set_listener(None)


def _approval(source: str, item: str, dialog_kind: str) -> Callable[[EmitRig, Any], Awaitable[None]]:
    async def fire(rig: EmitRig, _mp: Any) -> None:
        from src.core.approvals.inbox import ApprovalsInbox
        from src.core.notifications.sources.approvals import ApprovalsSource
        from tests.python.notifications.test_sources_approvals_alerts import _Provider, _watcher

        provider = _Provider()
        inbox = ApprovalsInbox(rig.frames.append)
        inbox.register(provider)
        rows = [{"id": "act_1", "target_session_id": SESSION}]
        watcher = _watcher(dialog_kind, sid=SESSION)
        inbox.on_gain_ids(ApprovalsSource(lambda: watcher, lambda: rig.manager, lambda: SimpleNamespace(list=lambda: rows)).on_gain)
        provider.entries = {(source, item, "fp")}
        inbox.refresh()
    return fire



NEEDS, SESS, MSG, AUTO, SWARM, HEALTH, SEC, AUTOM, APP = (
    "needs_you", "sessions", "messages", "auto_answers", "swarm", "health", "security", "automations", "app")

ROWS = (
    Row("session.permission", NEEDS, TOAST, _attention("PermissionRequest", REASON_PERMISSION)),
    Row("session.question", NEEDS, TOAST, _attention("PermissionRequest", REASON_QUESTION)),
    Row("session.plan_approval", NEEDS, TOAST, _attention("PermissionRequest", "plan_approval")),
    Row("session.attention", NEEDS, TOAST, _attention("Notification", None)),
    Row("approval.agent_action", NEEDS, INBOX, _approval("agent_action", "act_1", "permission")),
    Row("approval.folder_trust", NEEDS, NONE, _approval("dialog", f"dlg:{SESSION}:abcd1234abcd1234", "folder_trust")),
    Row("session.finished", SESS, TOAST, _attention("Stop", REASON_TURN_ENDED)),
    Row("session.died", SESS, FRAME, _died),
    Row("session.auto_slept", SESS, FRAME, _auto_slept),
    Row("agent.update_ready", SESS, NONE, _agent_update),
    Row("account.switched", SESS, FRAME, _account_switched),
    Row("app.restore_offer", SESS, NONE, _restore),
    Row("session.terminal_notice", SESS, TOAST, _terminal_notice),
    Row("agent.message", MSG, TOAST, _agent_message),
    Row("plugin.notice", MSG, TOAST, _plugin_notice),
    Row("session.skill_tripwire", MSG, TOAST, _skill_tripwire),
    Row("session.beast_approved", AUTO, NONE, _beast),
    Row("session.auto_accepted", AUTO, NONE, _auto_accepted),
    Row("swarm.alert", SWARM, NONE, _swarm("alert:immediate:stuck:3")),
    Row("swarm.flash", SWARM, NONE, _swarm("alert:flash:3:ab12")),
    Row("swarm.question_climbed", SWARM, NONE, _question_climbed),
    Row("alert.self_check", HEALTH, BELL, _alert("self_check.tmux", "app_alert.self_check.tmux.title")),
    Row("alert.save_pipeline", HEALTH, BELL, _alert("backup_health.usb_backup", "app_alert.backup_health.usb_backup.title")),
    Row("alert.account", HEALTH, BELL, _alert("account.signed_out", "app_alert.account.signed_out.title")),
    Row("alert.phone_link", HEALTH, BELL, _alert("phone_link.repair", "app_alert.phone_link.repair.title")),
    Row("alert.plugin", HEALTH, BELL, _plugin_runtime),
    Row("pack.skills", HEALTH, BELL, _alert("pack_skills.alpha_changed", "app_alert.pack_skills.alpha_changed.title")),
    Row("alert.notifications", HEALTH, BELL, _destination_disabled, outside=False),
    Row("provider.needs_login", HEALTH, NONE, _needs_login),
    Row("alert.other", HEALTH, BELL, _alert("widget.report.emit", "app_alert.widget.report.title")),
    Row("computer.wrong_code", SEC, NONE, _wrong_code),
    Row("computer.knock", SEC, NONE, _knock),
    Row("computer.link_cert", SEC, NONE, _link_cert),
    Row("automation_report", AUTOM, BELL, lambda r, m: _automation(r, m, "report")),
    Row("automation_failed", AUTOM, BELL, lambda r, m: _automation(r, m, "failed")),
    Row("automation_notice", AUTOM, BELL, lambda r, m: _automation(r, m, "notice")),
    Row("app.update_available", APP, NONE, _update),
    Row("stats.tripwire", APP, FRAME, _stats_tripwire, outside=False),
    Row("dev.shape_unrecognized", APP, FRAME, _shape, outside=False),
)
_BY_ID: Dict[str, Row] = {row.type_id: row for row in ROWS}


@pytest_asyncio.fixture()
async def rig(tmp_path, monkeypatch):
    wired = EmitRig(tmp_path, monkeypatch)
    await wired.start()
    yield wired
    await wired.stop()


def test_every_registered_type_has_exactly_one_row() -> None:
    registered = [t.id for t in types.TYPES]
    assert len(ROWS) == len(_BY_ID), "a type has two rows"
    assert sorted(_BY_ID) == sorted(registered), (
        f"missing rows: {sorted(set(registered) - set(_BY_ID))}; stale rows: {sorted(set(_BY_ID) - set(registered))}")
    assert len(registered) == 39


@pytest.mark.parametrize("row", ROWS, ids=[row.type_id for row in ROWS])
async def test_the_type_reaches_the_engine_the_screen_and_a_destination(row: Row, rig: EmitRig, monkeypatch) -> None:
    registered = types.get_type(row.type_id)
    assert registered.family == row.group, "the group differs from plan 7.4"

    await row.fire(rig, monkeypatch)
    await rig.settle()

    reached = [e for e in rig.handled if e.type_id == row.type_id]
    in_app_only = row.outside is False and not registered.match.alert_keys and not registered.match.alert_prefixes
    if in_app_only:
        assert reached == []
        await rig.engine.handle(_probe(row.type_id))
        await rig.engine.join()
    else:
        assert len(reached) == 1, f"the engine saw {[e.type_id for e in rig.handled]}"

    if row.screen == TOAST:
        cards = [json.loads(ToastNewMessage(toast=t).model_dump_json())["toast"] for t in rig.toasts]
        assert [c["notify_type"] for c in cards] == [row.type_id]
    elif row.screen == BELL:
        raised = [f for f in rig.bell if f.get("type") == "app_alert.raised"]
        assert len(raised) == 1 and raised[0]["notify_type"] == row.type_id, raised
        assert types.type_for_alert_key(raised[0]["key"]) == row.type_id
    elif row.screen == FRAME:
        assert [f["type"] for f in rig.frames if f["type"] in registered.match.frames] == list(registered.match.frames)
    elif row.screen == INBOX:
        assert any(f.get("type") == "approvals" for f in rig.frames), rig.frames
    else:
        assert rig.toasts == [] and not [f for f in rig.bell if f.get("type") == "app_alert.raised"]

    delivered = rig.delivered(row.type_id)
    if row.outside:
        assert len(delivered) == 1 and delivered[0].computer == "mini"
    else:
        assert delivered == [], "a type locked off the outside reached a destination"


def _probe(type_id: str) -> Any:
    from src.core.notifications.contracts import NotifyEvent

    return NotifyEvent(type_id=type_id, kind=type_id, title="t", ts=0.0, instance_key="probe")
