
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, Dict, List

from src.core.app_alerts import service, store
from src.core.approvals.extract import KIND_TRUST
from src.core.approvals.inbox import ApprovalsInbox
from src.core.notifications import contracts
from src.core.notifications.sources import alerts as alerts_source
from src.core.notifications.sources.approvals import ApprovalsSource


class _Provider:

    def __init__(self) -> None:
        self.entries: set = set()

    def signature(self) -> frozenset:
        return frozenset(self.entries)

    async def items(self) -> List[Dict[str, Any]]:
        return []


def _manager() -> Any:
    registry = SimpleNamespace(sessions={"ses_1": SimpleNamespace(tmux_session="cloude_api")})
    return SimpleNamespace(_registry=registry, _identity_for_live_name=lambda name: {"project_name": "api"},
                           _label_for_tmux_name=lambda name: "API")


REAL_TRUST = SimpleNamespace(
    question="Quick safety check: Is this a project you created or one you trust?", body="",
    rows=(SimpleNamespace(label="Yes, I trust this folder"), SimpleNamespace(label="No, exit")))


def _watcher(kind: str, dialog: Any = None, sid: str = "ses_1") -> Any:
    dialog = dialog or (REAL_TRUST if kind == KIND_TRUST else SimpleNamespace(question="Allow edit?", body="", rows=()))
    dialog = SimpleNamespace(kind=kind, question=dialog.question, body=dialog.body, rows=dialog.rows)
    obs = SimpleNamespace(evidence=SimpleNamespace(dialog=dialog))
    return SimpleNamespace(observation_for=lambda s: obs if s == sid else None)


def _wire(kind: str = "permission"):
    provider = _Provider()
    inbox = ApprovalsInbox(lambda frame: None)
    inbox.register(provider)
    store_rows = [{"id": "act_1", "target_session_id": "ses_1"}]
    source = ApprovalsSource(lambda: _watcher(kind), _manager, lambda: SimpleNamespace(list=lambda: store_rows))
    inbox.on_gain_ids(source.on_gain)
    return provider, inbox


def test_inbox_emits_agent_action_and_folder_trust_only(captured) -> None:
    provider, inbox = _wire(KIND_TRUST)
    provider.entries = {("agent_action", "act_1", "act_1"), ("dialog", "dlg:ses_1:abcd1234abcd1234", "fp")}
    inbox.refresh()
    assert sorted(e.type_id for e in captured) == ["approval.agent_action", "approval.folder_trust"]
    action = next(e for e in captured if e.type_id == "approval.agent_action")
    assert action.instance_key == "act_1" and action.open_item and action.project == "api" and action.session_id == "ses_1"


def _trust_events(item_id: str, dialog: Any, sid: str = "ses_1") -> List[Any]:
    got: List[Any] = []
    contracts.install_sink(got.append)
    ApprovalsSource(lambda: _watcher(KIND_TRUST, dialog, sid), _manager, lambda: SimpleNamespace(list=lambda: [])
                    ).on_gain([("dialog", item_id)])
    return got


def test_trust_word_without_real_trust_dialog_evidence_emits_nothing(captured) -> None:
    perm = SimpleNamespace(question="Do you want to edit trust_utils.py?", body="", rows=(SimpleNamespace(label="Yes"),))
    ask = SimpleNamespace(question="Do you trust the new vendor's API?", body="", rows=(SimpleNamespace(label="Yes"),))
    assert _trust_events("dlg:ses_1:abcd1234abcd1234", perm) == []
    assert _trust_events("dlg:ses_1:abcd1234abcd1234", ask) == []
    assert len(_trust_events("dlg:ses_1:abcd1234abcd1234", REAL_TRUST)) == 1
    codex = SimpleNamespace(question="Do you trust the contents of this directory?", body="", rows=())
    assert len(_trust_events("dlg:ses_1:abcd1234abcd1234", codex)) == 1


def test_adopted_session_item_id_is_parsed(captured) -> None:
    got = _trust_events("dlg:adopted:cloude_api:abcd1234abcd1234", REAL_TRUST, sid="adopted:cloude_api")
    assert len(got) == 1 and got[0].type_id == "approval.folder_trust"
    assert len(_trust_events("dlg:ses_1:abcd1234abcd1234", REAL_TRUST)) == 1


def test_every_other_dialog_kind_emits_nothing_it_has_a_watcher_toast_twin(captured) -> None:
    for kind in ("permission", "question", "plan_approval", "elicitation"):
        provider, inbox = _wire(kind)
        provider.entries = {("dialog", "dlg:ses_1:abcd1234abcd1234", "fp")}
        inbox.refresh()
    assert captured == []


def test_a_removal_or_an_unchanged_refresh_does_not_emit_again(captured) -> None:
    provider, inbox = _wire(KIND_TRUST)
    provider.entries = {("agent_action", "act_1", "act_1")}
    inbox.refresh()
    inbox.refresh()
    provider.entries = set()
    inbox.refresh()
    assert len(captured) == 1


def test_a_listener_that_raises_does_not_break_refresh() -> None:
    inbox = ApprovalsInbox(lambda frame: None)
    provider = _Provider()
    inbox.register(provider)

    def boom(gained):
        raise ValueError("x")

    inbox.on_gain_ids(boom)
    provider.entries = {("agent_action", "a", "a")}
    assert inbox.refresh() is True




def _row(key: str = "pipeline.llm_all_down", severity: str = "error") -> Dict[str, Any]:
    return {"id": 7, "key": key, "severity": severity, "state": "active", "count": 1}


def test_listener_hops_onto_the_loop_from_a_worker_thread(captured) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        listener = alerts_source.make_listener(loop)
        done = threading.Event()
        loop_thread = threading.get_ident()
        emitted_on: List[int] = []
        contracts.install_sink(lambda event: (emitted_on.append(threading.get_ident()), captured.append(event)))
        threading.Thread(target=lambda: (listener(_row()), done.set())).start()
        await asyncio.sleep(0.05)
        assert done.is_set() and len(captured) == 1
        assert emitted_on == [loop_thread], "the emit must run on the loop thread, not the producer's"

    captured.clear()
    asyncio.run(scenario())


def test_event_maps_the_key_with_type_for_alert_key(captured) -> None:
    assert alerts_source.event_for(_row("backup_health.usb_backup")).type_id == "alert.save_pipeline"
    assert alerts_source.event_for(_row("widget.report.x")).type_id == "alert.other"
    assert alerts_source.event_for(_row("cplug.foo")).type_id == "alert.plugin"
    assert alerts_source.event_for(_row(severity="error")).severity == contracts.SEVERITY_ERROR


def test_raise_alert_listener_fires_on_new_rows_only(tmp_path, captured) -> None:
    from src.core.db import db_path_for
    from src.core.db_migration import ensure_db_migrated

    assert ensure_db_migrated(tmp_path).status == "ok"
    path = db_path_for(tmp_path)
    seen: List[Any] = []
    frames: List[Any] = []
    service.configure(path, frames.append)
    service.on_raised(seen.append)
    try:
        kwargs = dict(source="t", severity="error", title_key="app_alert.backup_health.usb_backup.title", db_path=path)
        first = service.raise_alert("backup_health.usb_backup", **kwargs)
        service.raise_alert("backup_health.usb_backup", **kwargs)
        assert first is not None and len(seen) == 1 and seen[0]["key"] == "backup_health.usb_backup"
        assert frames[0]["notify_type"] == "alert.save_pipeline"
        listed = service.list_view(path, include_closed=False, limit=10)["alerts"]
        assert listed[0]["notify_type"] == "alert.save_pipeline"
        service.resolve("backup_health.usb_backup", db_path=path)
        assert len(seen) == 1
        service.raise_alert("backup_health.usb_backup", **kwargs)
        assert len(seen) == 2
    finally:
        service.configure(None, None)
    assert service._raised_listeners == []


def test_notify_type_is_stamped_on_the_frame_and_the_serialized_row() -> None:
    row = {"id": 1, "key": "self_check.files", "severity": "warn", "state": "active", "count": 2,
           "notify_type": "alert.self_check"}
    assert service.build_frame(row, store.EV_RAISED)["notify_type"] == "alert.self_check"
