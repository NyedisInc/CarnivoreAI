
from __future__ import annotations

from typing import List

import pytest

from src.cplugs.huddle import CPLUG, send_queue
from src.cplugs.sdk import old_names
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
ROUTES = [
    ("post", "/lists/12/tell", "/lists/12/send", {"target": "ses_old"}),
    ("post", "/tell", "/send", {"lists": ["12"]}),
    ("put", "/lists/12/tell-target", "/lists/12/send-target", {"target": "ses_old"}),
    ("get", "/tell-queue", "/send-queue", None),
    ("post", "/tell-queue/flush", "/send-queue/flush", {}),
]


def call(client, method: str, path: str, body):
    return getattr(client, method)(f"{BASE}{path}", **({} if body is None else {"json": body}))


@pytest.mark.parametrize("method,old,new,body", ROUTES)
def test_a_retired_route_path_is_gone_and_its_new_path_answers(client, app, pasted, method, old, new, body):
    note(app, "ses_old", "12", 100.0)
    assert call(client, method, new, body).status_code == 200
    assert call(client, method, old, body).status_code in (404, 405)


def test_no_retired_route_is_declared_to_the_usage_counter():
    assert old_names.declared().get("route", []) == []


def test_the_queue_names_only_the_current_topic_from_its_one_push():
    named: List[str] = []

    class Ctx:
        def notify(self, name, key=None):
            named.append(name)

    send_queue._push(Ctx())
    assert named == ["sendq"]
    assert "tellq" not in CPLUG.manifest.surfaces.topics and "sendq" in CPLUG.manifest.surfaces.topics


def test_the_queue_window_reads_the_new_keys_only():
    assert send_queue.window({"sendQuietSeconds": 100, "sendCapSeconds": 200}) == (100.0, 200.0)
    assert send_queue.window({"tellQuietSeconds": 100, "tellCapSeconds": 200}) != (100.0, 200.0)


def test_the_shipped_manifest_has_no_setting_alias_and_no_tool_alias():
    m = CPLUG.manifest
    assert dict(m.settings_aliases) == {} and dict(m.mcp_tool_aliases) == {}
    assert not {"heldTellMinutes", "tellQuietSeconds", "tellCapSeconds"} & set(m.settings_schema["fields"])
