
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_td_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_td_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from dataclasses import replace

from src.core.attention.toast_detail import detail_for
from src.core.attention.toast_facts import (
    SNIPPET_CHARS,
    TARGET_CHARS,
    ToastFacts,
    extract_toast_facts,
)
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.attention_wiring import build_attention_watcher
from src.core.sessions.toast_inbox import ToastInbox
from src.models.notifications import ToastDetail
from tests.test_attention_wiring import (  # noqa: F401
    RecordingManager,
    busy_pair,
    done_pair,
    gathered_file_tiers,
    no_real_pulls,
)
from tests.test_toast_cross_session import _app, _session

FAKE_TOKEN = "ghp_" + "a1B2" * 9


def assistant(*blocks, sidechain=False, text=None):
    content = list(blocks)
    if text is not None:
        content.insert(0, {"type": "text", "text": text})
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"content": content}}


def tool_use(name, tool_input, tool_id="tu_1"):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def tool_result(tool_id="tu_1"):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]}}




def test_a_window_ending_on_an_unanswered_bash_names_the_tool_and_command():
    facts = extract_toast_facts([
        assistant(tool_use("Bash", {"command": "git push origin master"}),
                  text="pushing the branch now"),
    ])
    assert facts.pending_tool == "Bash"
    assert facts.pending_target == "git push origin master"
    assert facts.last_text == "pushing the branch now"


def test_an_answered_call_is_not_pending():
    facts = extract_toast_facts([
        assistant(tool_use("Bash", {"command": "ls"})),
        tool_result(),
    ])
    assert facts.pending_tool is None
    assert facts.pending_target is None


def test_a_sidechain_record_is_not_the_sessions_words():
    facts = extract_toast_facts([
        assistant(text="main says this"),
        assistant(text="a sub-agent says this", sidechain=True),
    ])
    assert facts.last_text == "main says this"


def test_a_credential_in_a_command_or_a_snippet_is_redacted():
    facts = extract_toast_facts([
        assistant(tool_use("Bash", {"command": "curl -H 'token " + FAKE_TOKEN + "'"}),
                  text="using " + FAKE_TOKEN),
    ])
    assert FAKE_TOKEN not in (facts.pending_target or "")
    assert FAKE_TOKEN not in (facts.last_text or "")
    assert "[redacted]" in facts.pending_target
    assert "[redacted]" in facts.last_text


def test_a_long_snippet_is_bounded():
    facts = extract_toast_facts([assistant(text="word " * 400)])
    assert len(facts.last_text) <= SNIPPET_CHARS


def test_garbage_never_raises():
    assert extract_toast_facts([None, 3, "x", {"type": "assistant"}]) == ToastFacts()


def test_the_classifier_carries_the_facts_on_the_one_observation():
    facts = classify_transcript_records([assistant(text="done here")])
    assert facts.toast_facts is not None
    assert facts.toast_facts.last_text == "done here"




def test_a_permission_detail_names_the_tool_and_a_bounded_target():
    facts = ToastFacts(last_text="about to push", pending_tool="Bash",
                       pending_target="x" * 150)
    detail = detail_for("permission", facts)
    assert detail.reason == "permission"
    assert detail.tool == "Bash"
    assert len(detail.target) <= TARGET_CHARS
    assert detail.snippet == "about to push"


def test_a_finished_turn_names_no_tool():
    facts = ToastFacts(last_text="all done", pending_tool="Bash", pending_target="ls")
    detail = detail_for("turn_ended", facts)
    assert detail.tool is None and detail.target is None
    assert detail.snippet == "all done"


def test_a_question_shows_its_own_text_as_the_snippet():
    facts = extract_toast_facts([
        assistant(tool_use("AskUserQuestion", {"questions": [{"question": "ship it?"}]}),
                  text="one thing first"),
    ])
    detail = detail_for("question", facts)
    assert detail.tool == "AskUserQuestion"
    assert detail.snippet == "ship it?"
    assert detail.target is None


def test_no_facts_still_carries_the_reason():
    assert detail_for("input", None) == ToastDetail(reason="input")




def _stored(inbox):
    toast, _ = inbox.store("ses_1", kind="Stop", title="Your turn", body=None,
                           color=None, session_label=None, session_name=None)
    return toast


def test_describe_bumps_the_version_only_on_a_real_change():
    inbox = ToastInbox()
    toast = _stored(inbox)
    start = toast.version
    inbox.describe("ses_1", toast.id, ToastDetail(reason="turn_ended", snippet="a"))
    assert toast.version == start + 1
    inbox.describe("ses_1", toast.id, ToastDetail(reason="turn_ended", snippet="a"))
    assert toast.version == start + 1, "an identical detail must not re-render clients"
    inbox.describe("ses_1", toast.id, ToastDetail(reason="turn_ended", snippet="b"))
    assert toast.version == start + 2


def test_describe_leaves_an_acknowledged_record_alone():
    inbox = ToastInbox()
    toast = _stored(inbox)
    inbox.ack("ses_1", toast.id, reason="dismissed")
    version = toast.version
    inbox.describe("ses_1", toast.id, ToastDetail(reason="turn_ended", snippet="x"))
    assert toast.detail is None and toast.version == version


def test_describe_on_an_unknown_record_answers_none():
    assert ToastInbox().describe("ses_1", "nope", ToastDetail()) is None




def test_the_raise_site_stamps_the_detail_from_the_same_observation(no_real_pulls):
    words = ToastFacts(last_text="the build is green")

    async def drive():
        registry_record, transcript = done_pair()
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": done_pair()})
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        manager._reads["cloude_a"] = busy_pair()
        await watcher.tick_once()
        manager._reads["cloude_a"] = (registry_record, replace(transcript, toast_facts=words))
        await watcher.tick_once()
        return manager

    manager = asyncio.run(drive())
    assert manager.toasts, "no toast was raised, so nothing below would be checked"
    toast = manager.toasts[-1]
    assert toast.detail == ToastDetail(reason="turn_ended", snippet="the build is green")
    assert toast.title == "Your turn" and toast.body is None


def test_an_edge_with_no_words_still_carries_its_reason(no_real_pulls):

    async def drive():
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": done_pair()})
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        manager._reads["cloude_a"] = busy_pair()
        await watcher.tick_once()
        manager._reads["cloude_a"] = done_pair()
        await watcher.tick_once()
        return manager

    manager = asyncio.run(drive())
    assert manager.toasts
    assert manager.toasts[-1].detail == ToastDetail(reason="turn_ended")




def test_the_synthetic_create_route_accepts_a_detail(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "sa", tmp_path / "a")
    res = client.post("/api/v1/sessions/sa/toasts", json={
        "kind": "PermissionRequest", "title": "needs your permission",
        "detail": {"reason": "permission", "tool": "Bash", "target": "git push",
                   "snippet": "pushing"},
    })
    assert res.status_code == 201, res.text
    assert res.json()["detail"]["tool"] == "Bash"
    listed = client.get("/api/v1/toasts").json()["toasts"]
    assert [t["detail"]["target"] for t in listed] == ["git push"], (
        "the cross-screen poll is how every other screen sees the card"
    )


def test_the_route_without_a_detail_is_unchanged(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "sa", tmp_path / "a")
    res = client.post("/api/v1/sessions/sa/toasts",
                      json={"kind": "Stop", "title": "Your turn"})
    assert res.status_code == 201
    assert res.json()["detail"] is None

