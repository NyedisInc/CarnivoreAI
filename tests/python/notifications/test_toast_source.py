
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

import pytest

from src.core.notifications import types as T
from src.core.notifications.sources import toast as toast_source
from src.models.notifications import Toast

ROOT = Path(__file__).resolve().parents[3]
_ALLOWED_CALLS = ("attention_notify_type", "plugin_notify_type")


def _record_toast_calls() -> List[ast.Call]:
    calls: List[ast.Call] = []
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")) == "record_toast":
                    node.path = str(path.relative_to(ROOT))  # type: ignore[attr-defined]
                    calls.append(node)
    return calls


def test_every_record_toast_caller_passes_a_registered_notify_type() -> None:
    calls = _record_toast_calls()
    paths = {c.path for c in calls}  # type: ignore[attr-defined]
    assert len(calls) >= 4 and "src/api/session_toast_routes.py" in paths
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "notify_type" in kw, call.path  # type: ignore[attr-defined]
        value = kw["notify_type"]
        if isinstance(value, ast.Constant):
            assert T.is_registered(value.value), (call.path, value.value)  # type: ignore[attr-defined]
        else:
            assert isinstance(value, ast.Call) and (
                getattr(value.func, "attr", getattr(value.func, "id", "")) in _ALLOWED_CALLS
            ), call.path  # type: ignore[attr-defined]


def test_attention_notify_type_table_is_registered_and_complete() -> None:
    cases = {
        ("Stop", "turn_ended"): "session.finished",
        ("PermissionRequest", "permission"): "session.permission",
        ("PermissionRequest", "question"): "session.question",
        ("PermissionRequest", "plan_approval"): "session.plan_approval",
        ("PermissionRequest", None): "session.permission",
        ("Notification", "input"): "session.attention",
    }
    for (kind, reason), expected in cases.items():
        assert toast_source.attention_notify_type(kind, reason) == expected
        assert T.is_registered(expected)
    with pytest.raises(ValueError):
        toast_source.attention_notify_type("Mystery", "input")


def test_plugin_notify_type_keeps_a_plugin_inside_its_own_registered_types(monkeypatch) -> None:
    from src.cplugs.host.capabilities import plugin_notify_type

    monkeypatch.setattr(T, "is_registered", lambda type_id: type_id == "cplug.acme.thing")
    assert plugin_notify_type("acme", "cplug.acme.thing") == "cplug.acme.thing"
    assert plugin_notify_type("huddle", "cplug.acme.thing") == "plugin.notice"
    assert plugin_notify_type("acme", "cplug.acme.nope") == "plugin.notice"
    assert plugin_notify_type("acme", "session.finished") == "plugin.notice"
    assert plugin_notify_type("acme", None) == "plugin.notice"


def test_toast_model_carries_notify_type_and_defaults_to_none() -> None:
    base = dict(id="a", session_id="s", kind="Stop", title="t")
    assert Toast(**base).notify_type is None
    assert Toast(**base, notify_type="session.finished").model_dump()["notify_type"] == "session.finished"


def test_inbox_stamps_notify_type_on_create_and_supersession() -> None:
    from src.core.sessions.toast_inbox import ToastInbox

    inbox = ToastInbox()
    args = dict(kind="Stop", title="done", body=None, color=None, session_label=None, session_name=None)
    first, superseded = inbox.store("ses_1", notify_type="session.finished", **args)
    assert first.notify_type == "session.finished" and not superseded
    second, superseded = inbox.store("ses_1", notify_type="session.finished", **args)
    assert superseded and second.id == first.id and second.notify_type == "session.finished"
    legacy, _ = inbox.store("ses_2", **args)
    assert legacy.notify_type is None
