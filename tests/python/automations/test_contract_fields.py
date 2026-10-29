
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.automations import contract, targets
from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import MIGRATIONS, storage_for
from src.cplugs.sdk.storage import CplugStorage, StorageSpec

CARD = {"kind": "swarm_card", "project_id": 1, "title": "t", "summary": "s"}
RECIPE = {"kind": "recipe", "recipe": "scrooge"}


async def _noop(ctx, automation, run):
    return m.RunOutcome()


@pytest.fixture
def store(tmp_path, monkeypatch):
    for kind in ("swarm_card", "recipe"):
        monkeypatch.setitem(targets.RUNNERS, kind, _noop)
    return AutomationStore(storage_for(tmp_path), clock=lambda: 1_800_000_000.0, notify=lambda _t: None)


def test_rung_one_rows_keep_skip_and_their_creator(tmp_path, monkeypatch):
    for kind in ("swarm_card",):
        monkeypatch.setitem(targets.RUNNERS, kind, _noop)
    old = CplugStorage(tmp_path / "automations", StorageSpec(db="automations.db", migrations=MIGRATIONS[:1]), tmp_path)
    conn = old.connect(True)
    conn.execute("INSERT INTO automations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("aut_old", "old", "old", 1, "0 7 * * 1", json.dumps(CARD), json.dumps({"notify": True, "notify_on": None}),
                  None, 3, "seed", "k", 1.0, 2.0))
    conn.commit()
    conn.close()
    store = AutomationStore(storage_for(tmp_path), clock=lambda: 1_800_000_000.0, notify=lambda _t: None)
    row = store.get("aut_old")
    assert row["revision"] == 3
    assert row["misfire"] == "skip" and row["updated_by"] == "seed" and row["created_actor"] == {"kind": "seed"}
    assert row["description"] == "" and row["project_id"] is None and row["retry_max"] == 0 and row["max_runtime_s"] is None
    assert store.changes("aut_old") == []


def test_new_row_defaults_to_run_once_and_logs_its_create(store):
    who = contract.actor("mcp", session_id="ses_1", tmux="cloude_x")
    made = store.create(name="n", cron="0 7 * * 1", target=CARD, description="weekly card", project_id=4, actor=who,
                        created_by="mcp")
    assert made["misfire"] == "run_once" and made["description"] == "weekly card" and made["project_id"] == 4
    assert made["created_actor"] == who and made["updated_actor"] == who
    log = store.changes(made["automation_id"])
    assert [c["action"] for c in log] == ["create"] and log[0]["actor"] == who and log[0]["before"] is None
    assert {c["field"] for c in log[0]["changes"]} >= {"name", "target", "description"}


def test_edit_logs_only_what_changed_and_delete_keeps_the_log(store):
    made = store.create(name="n", cron="0 7 * * 1", target=CARD)
    store.update(made["automation_id"], 1, actor=contract.actor("mcp", session_id="ses_2"), cron="0 8 * * 1", misfire="skip")
    edited = store.get(made["automation_id"])
    assert edited["updated_by"] == "mcp" and edited["updated_actor"]["session_id"] == "ses_2"
    newest = store.changes(made["automation_id"])[0]
    assert newest["action"] == "update"
    assert {c["field"] for c in newest["changes"]} == {"trigger", "misfire"}
    store.delete(made["automation_id"], contract.actor("app"))
    log = store.changes(made["automation_id"])
    assert [c["action"] for c in log] == ["delete", "update", "create"]
    assert log[0]["before"]["name"] == "n" and log[0]["after"] is None


def test_project_filter_and_contract_refusals(store):
    store.create(name="a", cron="0 7 * * 1", target=CARD, project_id=7)
    store.create(name="b", cron="0 7 * * 1", target=CARD)
    assert [r["name"] for r in store.list_all(7)] == ["a"] and len(store.list_all()) == 2
    for bad, code in (({"misfire": "late"}, "misfire_invalid"), ({"retry_max": 9}, "retry_invalid"),
                      ({"max_runtime_s": 5}, "max_runtime_invalid"), ({"description": "x" * 501}, "description_invalid")):
        with pytest.raises(m.AutomationInvalid) as exc:
            store.create(name=f"bad {code}", cron="0 7 * * 1", target=CARD, **bad)
        assert exc.value.code == code


def test_retries_are_refused_for_a_spending_target(store):
    with pytest.raises(m.AutomationInvalid) as exc:
        store.create(name="r", cron="0 7 * * 1", target=RECIPE, retry_max=1)
    assert exc.value.code == "retry_not_allowed"
    assert store.create(name="c", cron="0 7 * * 1", target=CARD, retry_max=2)["retry_max"] == 2


def test_mcp_request_carries_the_asking_agent():
    from src.core.mcp import automation_tools
    from src.api import automation_routes

    caller = SimpleNamespace(current_session_id="ses_9", session_id="ses_env", tmux_name="cloude_9", token_name="")
    manager = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    request = automation_tools._mcp_request(manager, caller)
    assert automation_routes.actor_of(request) == {"kind": "mcp", "session_id": "ses_9", "tmux": "cloude_9"}
    assert automation_routes.actor_of(SimpleNamespace()) == {"kind": "app"}


def test_every_automation_write_waits_unless_beast_covers_it_and_delete_always_waits():
    from src.core.mcp import automation_tools, beast_mode

    assert automation_tools.WRITE_TOOLS
    assert "automation_delete" in beast_mode.ALWAYS_WAITS and not beast_mode.eligible_action("automation_delete")
    assert all(beast_mode.eligible_action(name) for name in automation_tools.WRITE_TOOLS - {"automation_delete"})
