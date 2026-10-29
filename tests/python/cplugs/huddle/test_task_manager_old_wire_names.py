
from __future__ import annotations

from typing import List, Tuple

import pytest

from src.cplugs.huddle import old_routes, send_queue
from src.cplugs.sdk import manifest, old_names, settings_aliases
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
ROUTES = [
    ("post", "/lists/12/tell", "/lists/12/send", {"target": "ses_old"}),
    ("post", "/tell", "/send", {"lists": ["12"]}),
    ("put", "/lists/12/tell-target", "/lists/12/send-target", {"target": "ses_old"}),
    ("get", "/tell-queue", "/send-queue", None),
    ("post", "/tell-queue/flush", "/send-queue/flush", {}),
]


@pytest.fixture
def counted():
    seen: List[Tuple[str, str, str]] = []
    before = old_names._sink
    old_names.install_sink(lambda kind, name, via, caller: seen.append((kind, name, via)))
    yield seen
    old_names.install_sink(before)


def call(client, method: str, path: str, body):
    return getattr(client, method)(f"{BASE}{path}", **({} if body is None else {"json": body}))


@pytest.mark.parametrize("method,old,new,body", ROUTES)
def test_an_old_route_path_answers_like_its_new_path_and_only_the_old_one_is_counted(client, app, pasted, counted, method, old, new, body):
    note(app, "ses_old", "12", 100.0)
    fresh = call(client, method, new, body)
    assert counted == []
    retired = call(client, method, old, body)
    assert retired.status_code == fresh.status_code == 200
    assert counted == [("route", f"{method.upper()} /cplugs/huddle{old.replace('/lists/12', '/lists/{key}')}", "route")]


def test_every_retired_route_is_declared_so_the_report_can_show_it_as_zero():
    declared = old_names.declared()["route"]
    assert sorted(declared) == sorted(f"{e.split(' ', 1)[0]} /cplugs/huddle{e.split(' ', 1)[1]}" for e in old_routes.RETIRED)


def test_an_undeclared_route_is_refused_at_import_time():
    with pytest.raises(ValueError):
        old_routes.retired("POST", "/tell-everyone")


def test_the_queue_names_both_topics_from_its_one_push():
    named: List[str] = []

    class Ctx:
        def notify(self, name, key=None):
            named.append(name)

    send_queue._push(Ctx())
    assert named == ["sendq", "tellq"]


ALIASES = {"sendQuietSeconds": "tellQuietSeconds", "sendCapSeconds": "tellCapSeconds"}
DEFAULTS = {"sendQuietSeconds": 10, "sendCapSeconds": 45}


def test_a_value_saved_under_the_old_key_is_read_as_the_new_key_and_counted_once(counted):
    settings_aliases._counted.clear()
    out = settings_aliases.merged(DEFAULTS, {"tellQuietSeconds": 30}, ALIASES)
    assert (out["sendQuietSeconds"], out["sendCapSeconds"]) == (30, 45)
    settings_aliases.merged(DEFAULTS, {"tellQuietSeconds": 30}, ALIASES)
    assert counted == [("setting", "tellQuietSeconds", "route")]


def test_a_saved_new_key_beats_the_old_one_and_nothing_is_counted(counted):
    settings_aliases._counted.clear()
    out = settings_aliases.merged(DEFAULTS, {"tellQuietSeconds": 30, "sendQuietSeconds": 20}, ALIASES)
    assert out["sendQuietSeconds"] == 20 and counted == []


def test_a_write_of_an_old_key_is_stored_under_the_new_one(counted):
    settings_aliases._counted.clear()
    assert settings_aliases.translate({"tellCapSeconds": 60, "view": "area"}, ALIASES) == {"sendCapSeconds": 60, "view": "area"}
    assert counted == [("setting", "tellCapSeconds", "route")]


def test_the_queue_window_reads_the_new_keys():
    assert send_queue.window({"sendQuietSeconds": 100, "sendCapSeconds": 200}) == (100.0, 200.0)


def test_the_shipped_manifest_declares_the_aliases_and_the_old_key_is_not_a_current_setting():
    from src.cplugs.huddle import CPLUG

    m = CPLUG.manifest
    assert m.settings_aliases == {"heldSendMinutes": "heldTellMinutes", "sendQuietSeconds": "tellQuietSeconds", "sendCapSeconds": "tellCapSeconds"}
    assert not set(m.settings_aliases.values()) & set(m.settings_schema["fields"])


def test_the_manifest_refuses_an_alias_whose_current_key_is_not_a_setting_or_whose_old_key_still_is():
    schema = {"version": 1, "fields": {"a": {}}}
    with pytest.raises(manifest.ManifestError):
        manifest._settings_aliases("x", {"b": "a_old"}, schema)
    with pytest.raises(manifest.ManifestError):
        manifest._settings_aliases("x", {"a": "a"}, schema)
