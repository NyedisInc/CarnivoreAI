
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from src.core.mcp import pending
from src.core.mcp.approvals import display
from src.models.dialogs import ApprovalItem

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
HOME = os.path.expanduser("~")

CASES = [
    ("session_purge", {"target": "u1", "plan_fingerprint": "fp9"}, "",
     "PURGE asleep session trader for good: 4 rows. Plan fp9.", "trader", False,
     ("purge", "session", "trader", "danger")),
    ("session_delete", {}, "api", "DELETE session api (its tmux session is killed)", "", True,
     ("delete", "session", "api", "danger")),
    ("session_delete", {}, "api", "DELETE asleep session api", "", False, ("delete", "session", "api", "danger")),
    ("session_stop", {}, "api", "stop (sleep) the session", "", True, ("stop", "session", "api", "confirm")),
    ("session_wake", {"target": "u2"}, "api", "session_wake on asleep api", "", False,
     ("wake", "session", "api", "confirm")),
    ("project_move", {"project": 3, "new_root": f"{HOME}/Development/Org/Personal/trader", "move_folder": True,
                      "create_parents": False, "plan_fingerprint": "abc"}, "",
     'move project "trader" to "/x": rename the folder (2 sessions; plan abc)', "", False,
     ("move", "project", "trader", "confirm")),
    ("project_create", {"name": "demo", "path": f"{HOME}/carnivore-projects/demo"}, "",
     'create project "demo" in "/x"', "", False, ("create", "project", "demo", "confirm")),
    ("project_delete", {"project": 3}, "", 'DELETE project "trader" for good', "", False,
     ("delete", "project", "trader", "danger")),
    ("company_create", {"name": "Org", "parent_id": None}, "", 'create company "Org" at the top level', "", False,
     ("create", "company", "Org", "confirm")),
    ("company_rename", {"company_id": 7, "name": "New"}, "", 'rename "Org" to "New" (its projects stay)', "", False,
     ("rename", "company", "Org", "confirm")),
    ("company_delete", {"company_id": 7}, "", 'delete "Org" (its projects become orphaned)', "", False,
     ("delete", "company", "Org", "danger")),
    ("company_parent_set", {"company_id": 7, "parent_id": 2}, "",
     'move "Org" and every company under it to under "Home"', "", False, ("move", "company", "Org", "confirm")),
    ("company_hq_set", {"company_id": 7, "project_id": 3}, "",
     'make "trader" (project) the HQ project of "Org" (folders and sessions untouched)', "", False,
     ("set", "company_home_project", "Org", "confirm")),
    ("company_hq_set", {"company_id": 7, "project_id": None}, "",
     'clear the HQ project of "Org" (folders and sessions untouched)', "", False,
     ("clear", "company_home_project", "Org", "confirm")),
    ("session_dialog_answer", {"target": "u1", "choice": {"option": "Yes"}}, "api",
     "answer the dialog on api with option Yes", "", False, ("answer", "session_dialog", "api", "confirm")),
    ("session_dialog_questions_answer", {"target": "u1", "questions_fingerprint": "a" * 64,
                                         "answers": [{"option": "Blue"}, {"options": ["Cheese"], "other": "private words"}]}, "api",
     "answer 2 questions on api", "", False, ("answer", "session_dialog", "api", "confirm")),
    ("delegate", {"computer": "studio", "command": "npm test", "folder": f"{HOME}/Development/trader"}, "",
     'run on "studio": npm test', "", False, ("run", "job", "studio", "confirm")),
]

JARGON = ("tmux", "record", "row", "re-point", "fingerprint", "uuid", "epoch", "database")


def _catalog_keys() -> set:
    return set(re.findall(r"^\s*'([a-z0-9_.]+)':", CATALOG.read_text(encoding="utf-8"), flags=re.M))


@pytest.mark.parametrize("action,args,target,summary,confirm,live,want", CASES,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_display_leads_with_verb_object_name(action, args, target, summary, confirm, live, want) -> None:
    block = display.build(action, args, target, summary, plain="", confirm_text=confirm, live=live)
    assert (block["verb"], block["object"], block["name"], block["tone"]) == want
    assert 1 <= len(block["consequences"]) <= 3
    assert block["detail"][-1] == {"key": "summary", "value": summary}


@pytest.mark.parametrize("action,args,target,summary,confirm,live,want", CASES,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_every_emitted_key_is_in_the_catalog(action, args, target, summary, confirm, live, want) -> None:
    keys = _catalog_keys()
    block = display.build(action, args, target, summary, confirm_text=confirm, live=live)
    emitted = [f"approvals.display.verb.{block['verb']}", f"approvals.display.object.{block['object']}"]
    emitted += [f"approvals.display.c.{c['key']}" for c in block["consequences"]]
    emitted += [f"approvals.display.d.{d['key']}" for d in block["detail"]]
    assert [k for k in emitted if k not in keys] == []


def test_visible_lines_are_plain_words() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    shown = re.findall(r"^\s*'approvals\.display\.(?:verb|object|c)\.[a-z0-9_]+':\s*(['\"])(.*?)\1,\s*$", text, flags=re.M)
    assert shown, "no visible approval strings found"
    bad = [line for _, line in shown if any(word in line.lower() for word in JARGON)]
    assert bad == []


def test_the_style_guide_specimens_are_the_real_display_blocks(monkeypatch) -> None:
    import json

    monkeypatch.setenv("HOME", "/Users/you")
    path = Path(__file__).resolve().parents[3] / "web" / "src" / "style-guide" / "approval-specimens.json"
    specimens = json.loads(path.read_text(encoding="utf-8"))
    assert len(specimens) >= 20
    for spec in specimens:
        i = spec["input"]
        built = display.build(i["action"], i["args"], i["target"], i["summary"], plain=i["plain"],
                              confirm_text=i["confirm_text"], live=i["live"], beast_hint=i.get("beast_hint", False))
        assert built == spec["display"], spec["id"]


def test_move_shortens_the_visible_path_and_keeps_the_full_one_in_detail() -> None:
    root = f"{HOME}/Development/Org/Personal/trader"
    block = display.build("project_move", {"new_root": root, "move_folder": False, "plan_fingerprint": "abc"},
                          "", 'move project "trader" to "x"')
    assert block["consequences"][0] == {"key": "moves_to", "params": {"to": "~/Development/Org/Personal/trader"}}
    assert {"key": "new_root", "value": root} in block["detail"]
    assert {"key": "fingerprint", "value": "abc"} in block["detail"]


def test_a_tool_with_no_rule_keeps_its_own_sentence_and_reads_destructive_by_name() -> None:
    block = display.build("automation_delete", {"automation_id": 4}, "", "delete automation \"nightly\"",
                          plain="delete automation 'nightly' and its run history\n\n- field: a -> b")
    assert block["verb"] == "automation delete" and block["tone"] == "danger" and block["name"] == "nightly"
    assert block["consequences"] == [{"key": "summary",
                                      "params": {"text": "delete automation 'nightly' and its run history"}}]


def test_the_pending_row_and_the_inbox_model_carry_display_and_confirm_text() -> None:
    item = pending.PendingAction(id="act_1", created_at=0.0, caller_session_id="", caller_tmux="c",
                                 target_session_id="u1", target_tmux="", action="session_purge",
                                 args_summary="PURGE asleep session trader", args={"plan_fingerprint": "fp"},
                                 confirm_text="trader", target_name="trader")
    row = item.as_dict()
    assert row["display"]["verb"] == "purge" and row["display"]["name"] == "trader"
    shown = ApprovalItem(id="act_1", source="agent_action", session_id="u1", kind="session_purge",
                         confirm_text=row["confirm_text"], display=row["display"]).model_dump()
    assert shown["confirm_text"] == "trader"
    assert shown["display"]["tone"] == "danger"


def test_the_approvals_list_returns_the_agent_action_fields_the_card_reads(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from src.api import approvals_routes

    row = {"id": "act_x", "source": "agent_action", "session_id": "u1", "kind": "session_purge",
           "external_client": "ci-bot", "confirm_text": "trader",
           "display": display.build("session_purge", {}, "trader", "PURGE trader", confirm_text="trader")}

    class Inbox:
        version = 3

        async def list_items(self) -> list:
            return [dict(row)]

    async def no_peers(_open_db) -> list:
        return []

    monkeypatch.setattr(approvals_routes.peer_items, "peer_items", no_peers)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(approvals_inbox=Inbox())))
    answer = asyncio.run(approvals_routes.list_approvals(request, principal=SimpleNamespace(is_peer=False)))
    item = answer.model_dump()["items"][0]
    assert item["external_client"] == "ci-bot"
    assert item["confirm_text"] == "trader"
    assert item["display"]["verb"] == "purge"


def test_the_batch_answer_card_names_each_questions_picks_and_typed_text_redacted_and_cut() -> None:
    from src.core.mcp.dialog_tools import _batch_body, _shown_batch

    raw = {"target": "u1", "questions_fingerprint": "a" * 64,
           "answers": [{"option": "Blue"}, {"options": ["Cheese", "Ham"], "other": "private  words"}, {}]}
    shown = _shown_batch(_batch_body(raw))
    block = display.build("session_dialog_questions_answer", shown, "api", "answer 3 questions")
    assert (block["verb"], block["object"]) == ("answer", "session_dialog")
    assert block["consequences"][0] == {"key": "answers_all", "params": {
        "count": "3", "picks": '1. Blue; 2. Cheese, Ham, typed text "private words"; 3. left unanswered'}}
    secret = _shown_batch(_batch_body({"target": "u1", "questions_fingerprint": "a" * 64,
                                       "answers": [{"other": "key sk-ant-api03-" + "A" * 40}]}))
    assert "A" * 40 not in str(secret)
    long = display.build("session_dialog_questions_answer", {"answers": [{"option": "x" * 200}]}, "api", "s")
    assert long["consequences"][0]["params"]["picks"] == "1. " + "x" * 60 + "..."
    same = display.build("session_dialog_questions_answer", {"answers": [{"other": "p" * 60 + "one"}, {"other": "p" * 60 + "two"}]}, "api", "s")
    assert same["consequences"][0]["params"]["picks"].count("...") == 2
    many = display.build("session_dialog_questions_answer", {"answers": [{"option": "o" * 50}] * 30}, "api", "s")
    picks = many["consequences"][0]["params"]["picks"]
    assert len(picks) < 560 and picks.endswith("; ... and 22 more")
    one = display.build("session_dialog_questions_answer", {"answers": [{"options": ["l" * 50] * 10}, {"option": "b"}]}, "api", "s")
    cut = one["consequences"][0]["params"]["picks"]
    assert cut == ("1. " + ", ".join(["l" * 50] * 10))[:480] + "...; ... and 1 more"


def _secret_batch() -> tuple:
    from src.core.mcp.dialog_tools import _batch_body, _shown_batch

    key = "ghp_" + "aB3xY9" * 6
    answers = [{"option": f"pick {key}"}, {"options": ["ok", f"also {key}"]}] + [{"other": "t" * 90}] * 6
    shown = _shown_batch(_batch_body({"target": "u1", "questions_fingerprint": "a" * 64, "answers": answers}))
    return key, shown, display.build("session_dialog_questions_answer", shown, "api", "s")


def test_the_batch_answer_card_secret_label_is_starred() -> None:
    key, shown, block = _secret_batch()
    assert key not in str(shown) and key not in str(block) and "*" in shown["answers"][0]["option"]


def test_the_batch_answer_card_detail_carries_every_whole_pick() -> None:
    _, _, block = _secret_batch()
    rows = [r["value"] for r in block["detail"] if r["key"] == "answer"]
    assert rows[7] == '8. typed text "' + "t" * 90 + '"' and len(rows) == 8
    assert "and " in block["consequences"][0]["params"]["picks"]


def test_the_batch_answer_card_detail_keeps_spacing_and_the_line_flattens_it() -> None:
    from src.core.mcp.dialog_tools import _batch_body, _shown_batch

    shown = _shown_batch(_batch_body({"target": "u1", "questions_fingerprint": "a" * 64, "answers": [{"other": "a   b  "}]}))
    assert shown["answers"][0]["other"] == "a   b  "
    block = display.build("session_dialog_questions_answer", shown, "api", "s")
    assert [r["value"] for r in block["detail"] if r["key"] == "answer"] == ['1. typed text "a   b  "']
    assert block["consequences"][0]["params"]["picks"] == '1. typed text "a b"'


def test_the_delegate_hint_is_a_field_and_never_a_line() -> None:
    args = {"computer": "studio", "command": "npm test", "folder": f"{HOME}/Development/trader"}
    plain = display.build("delegate", args, "", "s")
    hinted = display.build("delegate", args, "", "s", beast_hint=True)
    assert "beast_hint" not in plain and hinted["beast_hint"] is True
    assert [c["key"] for c in plain["consequences"]] == [c["key"] for c in hinted["consequences"]] == ["delegate_runs", "delegate_copy"]
    assert hinted["consequences"][1]["params"]["folder"] == "~/Development/trader"
    other = display.build("session_stop", {}, "api", "s", beast_hint=True)
    assert "beast_hint" not in other


TASK_ARGS = {"computer": "studio", "folder": f"{HOME}/Development/trader", "task": "fix the retry path\nthen run the tests " + "x" * 200,
             "agent_type": "reviewer", "family": "claude", "permission_mode": "default", "model": "m1", "time_cap_minutes": 30}


def test_the_task_card_has_three_lines_in_order_and_the_whole_task_in_detail() -> None:
    block = display.build("delegate", TASK_ARGS, "", "s")
    assert [c["key"] for c in block["consequences"]] == ["delegate_agent_runs", "delegate_copy", "delegate_mode_ask"]
    first = block["consequences"][0]["params"]
    assert first["agent"] == "reviewer" and first["computer"] == "studio" and "\n" not in first["task"] and first["task"].endswith("...")
    rows = {r["key"]: r["value"] for r in block["detail"]}
    assert rows["task"] == TASK_ARGS["task"] and rows["agent_type"] == "reviewer" and rows["model"] == "m1" and rows["time_cap"] == "30"
    assert display.build("delegate", {**TASK_ARGS, "agent_type": ""}, "", "s")["consequences"][0]["params"]["agent"] == "an agent"


def test_an_install_is_the_second_line_in_both_forms_and_absent_without_one() -> None:
    cmd = {"computer": "studio", "command": "ffmpeg -i a b", "folder": f"{HOME}/Development/trader"}
    keys = [c["key"] for c in display.build("delegate", {**cmd, "installs": ["ffmpeg", "node"]}, "", "s")["consequences"]]
    assert keys == ["delegate_runs", "delegate_installs", "delegate_copy"]
    line = display.build("delegate", {**cmd, "installs": ["ffmpeg", "node"]}, "", "s")["consequences"][1]
    assert line["params"] == {"tools": "ffmpeg, node", "computer": "studio"}
    task = [c["key"] for c in display.build("delegate", {**TASK_ARGS, "installs": ["gh"]}, "", "s")["consequences"]]
    assert task == ["delegate_agent_runs", "delegate_installs", "delegate_copy", "delegate_mode_ask"]
    assert "delegate_installs" not in [c["key"] for c in display.build("delegate", {**cmd, "installs": []}, "", "s")["consequences"]]


@pytest.mark.parametrize("mode,key", [("bypassPermissions", "delegate_mode_bypass"), ("skip_all", "delegate_mode_bypass"),
                                      ("acceptEdits", "delegate_mode_edits"), ("manual", "delegate_mode_ask"), ("dontAsk", "delegate_mode_dontask"),
                                      ("auto", "delegate_mode_auto"), ("unknown", "delegate_mode_unknown"), ("nonsense", "delegate_mode_unknown")])
def test_the_worker_mode_line_names_the_mode_and_bypass_has_its_own_key(mode, key) -> None:
    block = display.build("delegate", {**TASK_ARGS, "permission_mode": mode}, "", "s")
    assert block["consequences"][2]["key"] == key
    text = re.search(rf"'approvals\.display\.c\.{key}': '([^']*)'", CATALOG.read_text(encoding="utf-8")).group(1)
    assert (mode in ("bypassPermissions", "skip_all")) == text.startswith("permission checks bypassed")


def test_every_task_card_key_is_in_the_catalog() -> None:
    keys = _catalog_keys()
    block = display.build("delegate", TASK_ARGS, "", "s")
    emitted = [f"approvals.display.c.{c['key']}" for c in block["consequences"]] + [f"approvals.display.d.{d['key']}" for d in block["detail"]]
    assert [k for k in emitted if k not in keys] == [] and "approvals.card.chip.beast_off" in keys


def test_would_approve_needs_beast_off_and_the_on_column_ticked(monkeypatch) -> None:
    from src.core.mcp import beast_mode

    monkeypatch.setattr(beast_mode, "eligible_action", lambda action: True)
    state = {"armed": False, "ticked": True}
    monkeypatch.setattr(beast_mode, "beast_enabled", lambda: state["armed"])
    monkeypatch.setattr(beast_mode, "ticked_in", lambda row, mode: state["ticked"])
    assert beast_mode.would_approve("delegate") is True
    state["armed"] = True
    assert beast_mode.would_approve("delegate") is False
    state.update(armed=False, ticked=False)
    assert beast_mode.would_approve("delegate") is False
    state["ticked"] = True
    assert beast_mode.would_approve("session_stop") is False


def test_as_dict_asks_beast_only_for_a_pending_delegate(monkeypatch) -> None:
    from src.core.mcp import beast_mode

    seen = []
    monkeypatch.setattr(beast_mode, "beast_enabled", lambda: seen.append("armed") or False)
    monkeypatch.setattr(beast_mode, "eligible_action", lambda action: True)
    monkeypatch.setattr(beast_mode, "ticked_in", lambda row, mode: True)
    base = dict(id="act_1", created_at=0.0, caller_session_id="", caller_tmux="c", target_session_id="", target_tmux="",
                args_summary="s")
    pending.PendingAction(action="session_stop", args={}, **base).as_dict()
    assert seen == []
    args = {"computer": "studio", "command": "npm test", "folder": "/x"}
    row = pending.PendingAction(action="delegate", args=args, **base).as_dict()
    assert row["display"]["beast_hint"] is True
    done = pending.PendingAction(action="delegate", args=args, status="approved", **base).as_dict()
    assert "beast_hint" not in done["display"]


def test_the_definition_is_a_detail_row_only_and_the_face_is_unchanged() -> None:
    prompt = "line one\x1b[31m red\x00\u202e\u200b\n" + "p" * 300
    definition = {"file": "rev.md", "prompt": prompt}
    block = display.build("delegate", {**TASK_ARGS, "definition": definition}, "", "s")
    assert block["consequences"] == display.build("delegate", TASK_ARGS, "", "s")["consequences"]
    row = next(r for r in block["detail"] if r["key"] == "definition")
    assert row["file"] == "rev.md" and row["value"] == "line one red\n" + "p" * 300
    assert "definition" not in [r["key"] for r in display.build("delegate", TASK_ARGS, "", "s")["detail"]]
