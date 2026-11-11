
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.approvals import deliver
from src.core.approvals.inbox import item_id
from src.core.notifications import contracts
from src.core.notifications.cards import settle, sources
from src.core.notifications.cards.build import build_card
from src.core.notifications.cards.live import LiveSources
from src.core.notifications.sources import agent_update, login, update
from src.core.session_git.reader import read_session_git
from tests.python.notifications.test_apns_card_payload import FP, event, permission_item
from tests.python.swarm.test_swarm_question_cards import QUESTION, SUMMARY, env  # noqa: F401

pytestmark = pytest.mark.asyncio


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True)


def _state(repo: Path, *, began: datetime, ended: datetime, items: List[Dict[str, Any]] = ()) -> SimpleNamespace:
    async def info(_sid: str) -> Any:
        return SimpleNamespace(tmux_session=None, session=SimpleNamespace(working_dir=str(repo)))

    async def read(_sid: str, directory: Path) -> Any:
        return read_session_git(directory)

    transcript = SimpleNamespace(newest_user_prompt_at=began, turn_end_at=ended)
    watcher = SimpleNamespace(observation_for=lambda _sid: SimpleNamespace(evidence=SimpleNamespace(transcript=transcript)))

    async def list_items() -> List[Dict[str, Any]]:
        return list(items)

    return SimpleNamespace(session_manager=SimpleNamespace(get_session_info=info), attention_watcher=watcher,
                           git_status_watch=SimpleNamespace(read=read), approvals_inbox=SimpleNamespace(list_items=list_items))


@pytest.fixture
def live(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("l1\nl2\nl3\nl4\nl5\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "one")
    (repo / "a.py").write_text("l1\nl3\nl4\nl5\nn1\nn2\nn3\n")
    (repo / "b.py").write_text("x\ny\n")
    began = datetime.now(timezone.utc)
    state = _state(repo, began=began, ended=began + timedelta(minutes=6, seconds=10), items=[permission_item()])
    sources.install(LiveSources(state))
    yield repo
    sources.install(None)


async def test_finished_card_carries_minutes_files_and_per_file_line_counts(live) -> None:
    built = await build_card(event("session.finished", kind="Stop"), "", detail=True)
    assert built.kind == "finished" and built.card["mins"] == 6 and built.card["nfiles"] == 2
    assert dict(zip(built.card["files"], built.card["stats"])) == {"a.py": [3, 1], "b.py": [2, 0]}


async def test_a_finished_turn_without_a_trusted_duration_or_diff_leaves_those_fields_out(live, tmp_path: Path) -> None:
    began = datetime.now(timezone.utc)
    sources.install(LiveSources(_state(tmp_path, began=began, ended=began + timedelta(seconds=5))))
    built = await build_card(event("session.finished", kind="Stop"), "", detail=True)
    assert not {"mins", "files", "stats"} & set(built.card)


async def test_permission_card_carries_the_session_folder_and_the_tool(live) -> None:
    item = {**permission_item(), "family": "claude", "body": "Bash command\n  npm run build in web/\n  Build the web bundle"}
    sources.install(LiveSources(_state(live, began=datetime.now(timezone.utc), ended=datetime.now(timezone.utc), items=[item])))
    built = await build_card(event("session.permission"), "", detail=True)
    assert built.card["dir"] == str(live) and built.card["tool"] == "bash command"


async def test_a_pdf_page_count_rides_the_file_card() -> None:
    from src.core.notify_media.intake import pdf_pages

    pages = pdf_pages(b"%PDF-1.4 << /Type /Pages /Kids [3 0 R] /Count 4 >>")
    hint = {"media": {"id": "0" * 32, "kind": "file", "name": "spec.pdf", "mime": "application/pdf", "bytes": 10, "pages": pages}}
    built = await build_card(event("agent.message", card_hint=hint), "", detail=True)
    assert built.kind == "file" and built.card["pages"] == 4


async def test_agent_update_card_has_the_oldest_running_version_the_installed_one_and_the_session_names(captured, tmp_path: Path, monkeypatch) -> None:
    runs = {"ses_1": (2, 1, 301), "ses_2": (2, 1, 305)}
    watcher = SimpleNamespace(
        observed_session_ids=lambda: list(runs),
        observation_for=lambda sid: SimpleNamespace(stale=False, evidence=SimpleNamespace(
            agent_family=None, registry=SimpleNamespace(known=True, pid=1, version=runs[sid]))))
    monkeypatch.setattr(agent_update, "agent_update_status", lambda **kw: SimpleNamespace(ready=True, installed="2.1.312"))
    names = {"ses_1": "billing-5", "ses_2": "api-docs"}
    monkeypatch.setattr(agent_update.common, "session_fields", lambda _m, sid: {"session_ref": names[sid]})
    assert agent_update.check_once(watcher, tmp_path, manager=object()) is True
    assert dict(captured[0].card_hint) == {"to": "2.1.312", "sessions": ["billing-5", "api-docs"], "ids": ["ses_1", "ses_2"], "from": "2.1.301"}
    built = await build_card(captured[0], "", detail=True)
    assert built.kind == "update" and built.card["from"] == "2.1.301" and built.card["sessions"] == ["billing-5", "api-docs"]
    many = await build_card(event("agent.update_ready", card_hint={"sessions": [f"n{i}" for i in range(9)], "ids": [f"s{i}" for i in range(9)]}), "")
    assert many.target["sessions"] == [f"s{i}" for i in range(6)] and len(many.card["sessions"]) == 6


async def test_app_update_card_has_the_installed_and_the_new_version(captured, tmp_path: Path) -> None:
    assert update.on_available("v1.16.8", tmp_path, current_version="v1.16.7") is True
    built = await build_card(captured[0], "", detail=True)
    assert built.kind == "appupdate" and (built.card["from"], built.card["to"]) == ("1.16.7", "1.16.8")


async def test_signin_card_has_the_account_and_why(captured) -> None:
    row = lambda state: SimpleNamespace(id="a", name="nyedis", provider="claude", credential_state=state, poke=None)  # noqa: E731
    watch = login.LoginWatch()
    watch.observe([row("ok")])
    watch.observe([row("refused")])
    built = await build_card(captured[0], "", detail=True)
    assert built.kind == "signin" and built.card["account"] == "nyedis" and built.card["reason"] == "renewal refused"


async def test_swarm_card_has_the_question_and_the_asker_path(env) -> None:  # noqa: F811
    from src.core.swarm.cards import phone

    env.conn.execute("INSERT INTO swarm_questions (id, text, state, created_at) VALUES (50, ?, 'open', '2026-10-07T00:00:00Z')", (QUESTION,))
    env.conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (50, ?, 'x')", (env.research["id"],))
    env.conn.commit()
    hint = await phone._card_hint(50)
    assert hint == {"ask": QUESTION, "asker_path": "Nyedis/Cobalt/Argent-Research"}
    built = await build_card(event("swarm.question_climbed", card_hint=hint), "", detail=True)
    assert built.kind == "swarm" and built.card["asker_path"] == "Nyedis/Cobalt/Argent-Research" and built.card["ask"].startswith("P7c")
    assert await phone._card_hint(999) == {}


@pytest.mark.parametrize("source,used,where", [
    (deliver.SOURCE_OWNER, False, "computer"), (deliver.SOURCE_OWNER_BANNER, False, "computer"),
    (deliver.SOURCE_OWNER_PHONE, False, "phone"), (deliver.SOURCE_AUTO, False, "auto"), (deliver.SOURCE_BEAST, False, "auto"),
    (None, False, "elsewhere"), (None, True, "phone")])
async def test_settle_where_comes_from_the_recorded_answer_source(source, used, where) -> None:
    ident = item_id("ses_w", FP)
    if source is not None:
        deliver.note_answered("ses_w", FP, source)
    sent = settle.Sent("d_1", "session.permission", "ses_w", "permission", "api-docs", "/p", "t", "cap", item=ident)
    assert settle.where_answered([sent], {"d_1"} if used else set()) == where
    deliver._ANSWERED_BY.pop(ident, None)
