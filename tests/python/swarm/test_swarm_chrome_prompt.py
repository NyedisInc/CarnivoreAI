
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.approvals.extract import extract_dialog
from src.core.swarm import delivery, launch
from tests.python.swarm.test_swarm_say_and_dialogs import pane, world  # noqa: F401

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"


def _agent(rank: str) -> dict:
    return {"id": 4, "slug": "t", "rank": rank, "effort": "low", "harness": "claude", "launch_profile": "claude-chrome"}


@pytest.mark.parametrize("rank", ["alpha", "company", "project"])
def test_upper_ranks_keep_no_chrome_even_on_a_chrome_profile(rank, tmp_path):
    argv = launch.launch_args_for_agent(_agent(rank), tmp_path, chrome_profile=True)
    assert argv[-1] == "--no-chrome" and "--chrome" not in argv


def test_task_agent_on_a_chrome_profile_keeps_chrome_and_others_get_no_chrome(tmp_path, monkeypatch):
    assert "--no-chrome" not in launch.launch_args_for_agent(_agent("task"), tmp_path, chrome_profile=True)
    assert launch.launch_args_for_agent(_agent("task"), tmp_path)[-1] == "--no-chrome"
    from src.core.launch_profiles.store import LaunchProfileStore

    profile = lambda flags=(): SimpleNamespace(id="claude-chrome", flags=list(flags), custom_command=None)  # noqa: E731
    for found, want in (([profile(flags=["--chrome"])], True), ([profile()], False)):
        monkeypatch.setattr(LaunchProfileStore, "list", lambda self, found=found: found)
        assert launch.profile_names_chrome(_agent("task")) is want
        assert ("--no-chrome" in launch.swarm_argv(_agent("task"), tmp_path)) is (not want)


def _set_rank(world, pane, rank: str) -> None:  # noqa: F811
    from contextlib import closing

    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(world.tmp))) as conn:
        conn.execute("UPDATE swarm_agents SET rank = ?, parent_id = NULL WHERE id = ?", (rank, pane.agent["id"]))
    pane.agent["rank"] = rank


def test_the_chrome_prompt_gets_one_card_across_two_refusals_and_the_answer_goes_through_the_core(world, pane, monkeypatch):  # noqa: F811
    import src.api.one_shot_routes as one_shot
    from fastapi import HTTPException

    _set_rank(world, pane, "task")

    async def refuse(request, session_id, text):
        raise HTTPException(status_code=409, detail={"code": "pane_dialog_open"})

    monkeypatch.setattr(one_shot, "paste_through_gates", refuse)
    dialog = extract_dialog((FIXTURES / "chrome_extension.txt").read_text(), "claude")
    assert dialog is not None and delivery._dialog_prefix(dialog) == delivery.CHOICE_PREFIX
    pane.dialog = dialog
    for _ in range(2):
        assert asyncio.run(delivery._attempt(pane.app_state, pane.agent["id"], "hi", "crosstalk", "data", "x:1", None)) == (
            "retry", "pane_dialog_open")
    (card,) = pane.cards()
    assert card["swarm_ref"].startswith(delivery.CHOICE_PREFIX) and card["kind"] == "question"
    assert card["text"].count("Claude in Chrome extension detected") == 1
    assert '"no, keep browser tools off"' in card["text"] and '"yes, use my browser"' in card["text"]
    assert not card["swarm_ref"].endswith(":no")
    asyncio.run(pane.facade.card_decided(card["swarm_ref"], "approve", "", "huddle:msg:7"))
    assert pane.answers == [("ses_1", dialog.fingerprint, "Yes, use my browser")]
    asyncio.run(pane.facade.card_decided(card["swarm_ref"], "answer", "no", "huddle:msg:8"))
    assert pane.answers[-1][2] == "No, keep browser tools off"


def test_the_rank_rule_covers_every_upper_rank_and_spares_feature_and_task():
    dialog = extract_dialog((FIXTURES / "chrome_extension.txt").read_text(), "claude")
    assert {r: delivery.choice_is_no_only({"rank": r}, dialog) for r in ("alpha", "company", "project", "feature", "task")} == {
        "alpha": True, "company": True, "project": True, "feature": False, "task": False}


@pytest.mark.parametrize("rank", ["company", "project"])
def test_an_upper_rank_card_offers_only_no_and_a_yes_is_refused_with_nothing_sent(rank, world, pane):  # noqa: F811
    from src.core.swarm import body

    _set_rank(world, pane, rank)
    pane.dialog = extract_dialog((FIXTURES / "chrome_extension.txt").read_text(), "claude")
    asyncio.run(delivery._maybe_dialog_card(pane.app_state, pane.agent, None, pane.info))
    (card,) = pane.cards()
    assert card["swarm_ref"] == f"choice:{pane.agent['id']}:{pane.dialog.fingerprint}:no"
    assert card["text"].count("Claude in Chrome extension detected") == 1
    assert '"no, keep browser tools off"' in card["text"] and "yes, use my browser" not in card["text"]
    with pytest.raises(body.BodyError, match="only the no option"):
        asyncio.run(pane.facade.card_decided(card["swarm_ref"], "approve", "", "huddle:msg:7"))
    old_ref = card["swarm_ref"][: -len(":no")]
    with pytest.raises(body.BodyError, match="only the no option"):
        asyncio.run(pane.facade.card_decided(old_ref, "approve", "", "huddle:msg:8"))
    assert pane.answers == []
    asyncio.run(pane.facade.card_decided(card["swarm_ref"], "answer", "no", "huddle:msg:9"))
    assert pane.answers == [("ses_1", pane.dialog.fingerprint, "No, keep browser tools off")]


def test_the_reader_extracts_the_chrome_prompt_from_a_claude_pane_with_no_registry_record(monkeypatch):
    from datetime import datetime, timezone

    from src.core import attention_reader as reader_module
    from src.core.attention.watcher import WatchTarget
    from src.core.attention_reader import AttentionEvidenceReader
    from src.core.session_instance_index import InstanceIndex
    from src.core.session_status_map import StatusMap

    screen = (FIXTURES / "chrome_extension.txt").read_text()
    manager = SimpleNamespace(
        _build_tmux_status_map=lambda: StatusMap({"cloude_0": {"status": "running", "pid": 100, "created_at_epoch": 1}},
                                                complete=True, socket="cloude"),
        _identity_for_instance=lambda name, epoch: {"agent_type": "claude"},
        _instance_index_for_listing=lambda *, socket, names: InstanceIndex(),
        tmux_socket_name=lambda: "cloude",
        _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(sessions={"cloude_0": SimpleNamespace(agent_type="claude")},
                                  backends={"cloude_0": SimpleNamespace(socket_name="cloude")}),
    )
    monkeypatch.setattr(reader_module, "read_registry_index", lambda: {})
    monkeypatch.setattr(reader_module, "read_instance_row", lambda *a, **k: {"claude_session_uuid": "uuid"})
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *a: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda socket, name, history=0: screen))
    reader = AttentionEvidenceReader(manager, lambda sid: (sid, 1))
    evidence = reader(WatchTarget("cloude_0", "cloude_0"), datetime(2026, 9, 20, tzinfo=timezone.utc))
    assert evidence.dialog is not None and delivery._dialog_prefix(evidence.dialog) == delivery.CHOICE_PREFIX


def test_a_choice_card_closes_when_the_prompt_is_answered_elsewhere_with_no_wake_open(world, pane):  # noqa: F811
    from src.core.swarm import watch

    _set_rank(world, pane, "task")
    pane.dialog = extract_dialog((FIXTURES / "chrome_extension.txt").read_text(), "claude")

    async def go() -> None:
        await delivery._maybe_dialog_card(pane.app_state, pane.agent, None, pane.info)
        assert len(pane.cards()) == 1 and delivery.has_dialog_cards(pane.agent["id"])
        pane.dialog = None
        watch.reset()
        watch.register(pane.app_state, "cloude_a", pane.agent["id"])
        watch._unsettled.clear()
        reading = SimpleNamespace(verdict=SimpleNamespace(reason="idle"), evidence=SimpleNamespace(dialog=None))
        watch.on_observation(SimpleNamespace(key="cloude_a@1"), reading)
        for _ in range(50):
            if pane.cards()[0]["state"] != "open":
                break
            await asyncio.sleep(0.1)

    asyncio.run(go())
    watch.reset()
    assert pane.cards()[0]["state"] != "open" and not delivery.has_dialog_cards(pane.agent["id"])
