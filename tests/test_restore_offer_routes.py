
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ro_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ro_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import restore_offer_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core import conversation_writers as cw  # noqa: E402
from src.core import session_journal_store as store  # noqa: E402
from src.core import session_restore_eval  # noqa: E402
from src.core.session_journal_measure import Measurement  # noqa: E402
from src.core.session_restore_offer import build_offer  # noqa: E402

T0 = "2026-09-23T10:00:00Z"
CONV_A, CONV_B = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"


def _row(uuid, name, conv):
    return {"session_uuid": uuid, "tmux_name": name, "tmux_created_epoch": 5, "title": name,
            "lifecycle": "running", "lifecycle_source": "create", "last_seen_running_at": T0,
            "archived_at": None, "claude_session_uuid": conv, "working_dir": "/w",
            "agent_type": "claude-chrome", "tmux_socket": "cloude"}


ROWS = [_row("A", "cloude_a", CONV_A), _row("B", "cloude_b", CONV_B)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    cands = [{"session_uuid": r["session_uuid"], "instance": f"{r['tmux_name']}@5",
              "tmux_name": r["tmux_name"], "tmux_epoch": 5, "title": r["title"], "folder": "/w",
              "conversation_measured": None, "observed_flags": ["--chrome", "--dangerously-skip-permissions"],
              "source": "record"} for r in ROWS]
    journal = store.empty_journal()
    journal["offer"] = build_offer(cands, reason="reboot", now_iso=T0, boot_epoch=9, previous_boot_epoch=1)
    store.save_journal(tmp_path, journal)

    writers = [cw.Writer(pid=4242, conversation=CONV_B, source=cw.SOURCE_PID_RECORD, cwd="/x")]
    m = Measurement(listing_ok=True, listing_complete=True, listing_reason="no_server",
                    panes=[], writers=writers, rows=ROWS, groups={}, rows_ok=True, writers_ok=True)
    monkeypatch.setattr(restore_offer_routes, "measure", lambda *a, **k: m)
    sigs = {"claude-chrome": frozenset({"--chrome", "--dangerously-skip-permissions"}),
            "claude-skip-permissions": frozenset({"--dangerously-skip-permissions"})}
    monkeypatch.setattr(session_restore_eval, "wrapper_table", lambda: (
        sigs, "claude-skip-permissions",
        [{"id": "claude-chrome", "label": "chrome"}, {"id": "claude-skip-permissions", "label": "claude"}]))
    monkeypatch.setattr(session_restore_eval, "load_trust_map", lambda: {})
    from src.core import session_imported_restart

    class _Dir:
        refuses = False
        working_dir = "/w"
        detail = ""

    monkeypatch.setattr(session_imported_restart, "resume_directory", lambda *a, **k: _Dir())

    calls = []

    async def fake_recreate(session_uuid, agent_type, *, get_manager, row_overrides=None):
        calls.append((session_uuid, agent_type, row_overrides))
        from src.api.recreate_routes import RecreateResponse
        return RecreateResponse(status="started", session_uuid=session_uuid, presence="gone",
                                conversation="resumed", tmux_session="carnivore_a", detail="ok")

    from src.api import recreate_action
    monkeypatch.setattr(recreate_action, "recreate_by_uuid", fake_recreate)

    tails = {}
    from src.core import session_restore_startup_check as startup_check
    monkeypatch.setattr(startup_check, "capture_pane_tail",
                        lambda *, socket, name, lines: tails.get(name))
    monkeypatch.setattr(startup_check.time, "sleep", lambda s: None)

    app = FastAPI()
    app.include_router(restore_offer_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = object()
    with TestClient(app) as client:
        client.tails = tails
        yield client, tmp_path, calls


def test_the_offer_marks_a_conversation_open_elsewhere_unselectable(env):
    client, _sd, _calls = env
    body = client.get("/api/v1/sessions/restore-offer").json()
    assert body["offer"]["reason"] == "reboot"
    by = {s["session_uuid"]: s for s in body["sessions"]}
    assert by["A"]["selectable"] is True and by["A"]["wrapper_default"] == "claude-chrome"
    assert by["B"]["selectable"] is False and by["B"]["blocked"] == "already_running_elsewhere"
    assert "4242" in by["B"]["detail"]
    assert by["A"]["wrapper_drops"]["claude-skip-permissions"] == ["--chrome"]


def test_accept_reopens_the_selectable_and_refuses_the_rest(env):
    client, sd, calls = env
    offer_id = client.get("/api/v1/sessions/restore-offer").json()["offer"]["id"]
    r = client.post("/api/v1/sessions/restore-offer/accept", json={
        "offer_id": offer_id,
        "sessions": [{"session_uuid": "A", "agent_type": "claude-chrome"},
                     {"session_uuid": "B", "agent_type": "claude-chrome"}]})
    assert r.status_code == 200, r.text
    out = {x["session_uuid"]: x["outcome"] for x in r.json()["results"]}
    assert out == {"A": "reopened", "B": "refused"}
    assert [c[0] for c in calls] == ["A"], "a refused session must never reach the create path"
    assert store.load_journal(sd).journal["offer"]["state"] == "accepted"
    log = store.human_log_path(sd).read_text()
    assert "restore_result" in log and "restore_accepted" in log


def test_an_unconfigured_wrapper_is_refused(env):
    client, _sd, calls = env
    offer_id = client.get("/api/v1/sessions/restore-offer").json()["offer"]["id"]
    r = client.post("/api/v1/sessions/restore-offer/accept", json={
        "offer_id": offer_id, "sessions": [{"session_uuid": "A", "agent_type": "rm -rf"}]})
    assert r.json()["results"][0]["outcome"] == "refused" and calls == []


def test_decline_is_remembered_and_cannot_be_repeated(env):
    client, sd, _calls = env
    offer_id = client.get("/api/v1/sessions/restore-offer").json()["offer"]["id"]
    assert client.post("/api/v1/sessions/restore-offer/decline", json={"offer_id": offer_id}).status_code == 200
    assert client.get("/api/v1/sessions/restore-offer").json()["offer"] is None
    assert client.post("/api/v1/sessions/restore-offer/decline", json={"offer_id": offer_id}).status_code == 409
    assert set(store.load_journal(sd).journal["declined"]) == {"A", "B"}


TRUST_DIALOG_TAIL = (
    " Quick safety check: Is this a project you created or one you trust?\n"
    " ❯ No, exit\n   Yes, I trust this folder\n Enter to confirm · Esc to cancel\n"
)


def test_a_reopen_parked_on_the_trust_prompt_says_so(env):
    client, sd, _calls = env
    client.tails["carnivore_a"] = TRUST_DIALOG_TAIL
    offer_id = client.get("/api/v1/sessions/restore-offer").json()["offer"]["id"]
    r = client.post("/api/v1/sessions/restore-offer/accept", json={
        "offer_id": offer_id, "sessions": [{"session_uuid": "A", "agent_type": "claude-chrome"}]})
    res = r.json()["results"][0]
    assert res["outcome"] == "reopened", "it did come back; the outcome is not downgraded"
    assert res["startup_gate"] == "awaiting_startup_prompt"
    assert res["detail"].startswith("reopened - waiting on the folder trust prompt")
    assert 'choose "Yes, I trust this folder"' in res["detail"]


def test_a_reopen_at_a_normal_prompt_is_plain_reopened(env):
    client, _sd, _calls = env
    client.tails["carnivore_a"] = "╭────╮\n│ > │\n╰────╯\n  ? for shortcuts\n"
    offer_id = client.get("/api/v1/sessions/restore-offer").json()["offer"]["id"]
    r = client.post("/api/v1/sessions/restore-offer/accept", json={
        "offer_id": offer_id, "sessions": [{"session_uuid": "A", "agent_type": "claude-chrome"}]})
    res = r.json()["results"][0]
    assert res["outcome"] == "reopened" and "startup_gate" not in res and res["detail"] == "ok"


def test_the_offer_says_which_folders_claude_will_ask_to_trust(env, monkeypatch):
    client, _sd, _calls = env
    from src.core import session_restore_eval as ev
    monkeypatch.setattr(ev, "load_trust_map", lambda: {"/w": False})
    by = {s["session_uuid"]: s for s in client.get("/api/v1/sessions/restore-offer").json()["sessions"]}
    assert by["A"]["folder_trust"] == "will_ask"
    monkeypatch.setattr(ev, "load_trust_map", lambda: {"/": True})
    by = {s["session_uuid"]: s for s in client.get("/api/v1/sessions/restore-offer").json()["sessions"]}
    assert by["A"]["folder_trust"] == "trusted", "a trusted parent covers the folder"
    monkeypatch.setattr(ev, "load_trust_map", lambda: None)
    by = {s["session_uuid"]: s for s in client.get("/api/v1/sessions/restore-offer").json()["sessions"]}
    assert by["A"]["folder_trust"] == "unknown", "an unreadable file is not a claim either way"


def test_a_stale_offer_id_is_refused_so_the_page_rereads(env):
    client, _sd, calls = env
    r = client.post("/api/v1/sessions/restore-offer/accept", json={
        "offer_id": "not-the-open-one", "sessions": [{"session_uuid": "A", "agent_type": "claude-chrome"}]})
    assert r.status_code == 409 and calls == []


def test_a_codex_row_is_looked_up_in_the_codex_rollout_store(env, monkeypatch):
    from src.core import session_imported_restart

    client, _sd, _calls = env
    seen = []

    class _Dir:
        refuses = False
        working_dir = "/w"
        detail = ""

    def _record(*args, **kwargs):
        seen.append((args, kwargs))
        return _Dir()

    monkeypatch.setattr(session_imported_restart, "resume_directory", _record)
    monkeypatch.setitem(ROWS[0], "agent_family", "codex")
    client.get("/api/v1/sessions/restore-offer")
    by_conv = {args[1]: kwargs.get("family") for args, kwargs in seen}
    assert by_conv, "the evaluation never asked for a resume directory, so nothing was measured"
    assert by_conv.get(CONV_A) == "codex"


def test_a_pane_that_died_after_the_offer_was_built_is_dropped(env, monkeypatch):
    from src.core.session_journal_observe import PaneFacts

    client, _sd, _calls = env
    husk = Measurement(listing_ok=True, listing_complete=True, listing_reason=None,
                       panes=[PaneFacts(name="cloude_a", epoch=5, dead=True)],
                       writers=[], rows=ROWS, groups={}, rows_ok=True, writers_ok=True)
    monkeypatch.setattr(restore_offer_routes, "measure", lambda *a, **k: husk)
    uuids = [s["session_uuid"] for s in client.get("/api/v1/sessions/restore-offer").json()["sessions"]]
    assert uuids == ["B"], "a measured-dead pane stayed in the offer"
