
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from src.core.attention.evidence import REASON_PANE_DEAD
from src.core.notifications import contracts
from src.core.notifications.cards import sources
from src.core.notifications.cards.build import build_card
from src.core.notifications.cards.live import LiveSources
from src.core.notifications.sources import died, died_capture, login
from src.core.notify_media import intake, store
from tests.socket_guard import TEST_SOCKET_NAME
from tests.python.notifications.test_apns_card_payload import event

pytestmark = pytest.mark.asyncio
SECRET = "ghp_" + "Kx9mQ2vL7pRt4WzN8bYc3JdF6hGs1AeUoXiP"


@pytest.fixture
def dead_pane(tmp_path) -> Iterator[tuple]:
    socket = TEST_SOCKET_NAME
    name = f"carnivore_s2c{uuid.uuid4().hex[:6]}"
    script = f"sleep 1; for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14; do echo line $i; done; echo \x1b[31mtoken {SECRET}\x1b[0m; exit 3"
    subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", "new-session", "-d", "-s", name, "-x", "100", "-y", "30", "sh", "-c", script],
                   check=True)
    subprocess.run(["tmux", "-L", socket, "set-option", "-t", f"={name}:", "remain-on-exit", "on"], check=True)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            shown = subprocess.run(["tmux", "-L", socket, "display-message", "-p", "-t", f"={name}:", "#{pane_dead}"],
                                   capture_output=True, text=True).stdout.strip()
            if shown == "1":
                break
            time.sleep(0.05)
        yield socket, name
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-session", "-t", f"={name}"], capture_output=True)


def test_a_dead_pane_gives_its_exit_code_and_last_lines_with_the_credential_starred(dead_pane) -> None:
    socket, name = dead_pane
    got = died_capture.read_dead_pane(socket, name)
    assert got["exit"] == 3
    assert len(got["tail"]) <= died_capture.MAX_LINES and sum(len(ln.encode()) + 1 for ln in got["tail"]) <= died_capture.MAX_BYTES
    joined = "\n".join(got["tail"])
    assert "line 14" in joined and "\x1b" not in joined and SECRET not in joined and "token ***" in joined.replace("*" * 5, "***")


def test_a_live_pane_is_never_read(tmp_path) -> None:
    socket, name = TEST_SOCKET_NAME, f"carnivore_live{uuid.uuid4().hex[:6]}"
    subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", "new-session", "-d", "-s", name, "sleep", "30"], check=True)
    try:
        assert died_capture.read_dead_pane(socket, name) == {}
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-session", "-t", f"={name}"], capture_output=True)


async def test_the_died_event_waits_for_one_capture_and_carries_it_and_details_off_drops_the_tail(dead_pane, monkeypatch) -> None:
    socket, name = dead_pane
    registry = SimpleNamespace(sessions={"ses_1": SimpleNamespace(tmux_session=name)}, backends={"ses_1": SimpleNamespace()})
    manager = SimpleNamespace(_registry=registry, _identity_for_live_name=lambda n: {"project_name": "api"},
                              _label_for_tmux_name=lambda n: "API", tmux_socket_name=lambda: socket)
    events: list = []
    monkeypatch.setattr(died.session_change_notice, "publish", lambda state, frame: None)
    tracker = died.DiedTracker(manager, object(), emit=events.append)
    target = SimpleNamespace(session_id="ses_1", key=f"{name}@7", generation=(1, 0))
    obs = SimpleNamespace(verdict=SimpleNamespace(reason=REASON_PANE_DEAD))
    tracker.observe(target, obs)
    assert tracker.observe(target, obs) is True and events == []
    await asyncio.gather(*tracker._tasks)
    assert events[0].card_hint["exit"] == 3 and "line 14" in "\n".join(events[0].card_hint["tail"])
    on = await build_card(events[0], "", detail=True)
    off = await build_card(events[0], "", detail=False)
    assert on.kind == "died" and on.card["tail"] and on.card["exit"] == 3
    assert "tail" not in off.card and off.card["exit"] == 3


def test_tidy_caps_lines_and_bytes_and_strips_ansi() -> None:
    raw = ("\x1b[1m" + "\n".join(f"line {i} " + "x" * 200 for i in range(40)) + "\x1b[0m\n\n").encode()
    lines = died_capture.tidy(raw)
    assert 0 < len(lines) <= 12 and sum(len(ln.encode()) + 1 for ln in lines) <= 1024 and "\x1b" not in "".join(lines)
    assert lines[-1].startswith("line 39")


@pytest.fixture
def media(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir(mode=0o700)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(store, "media_dir", lambda: root)
    return project


async def test_a_text_file_carries_its_first_lines_and_a_pdf_does_not(media) -> None:
    (media / "notes.txt").write_text("\n# mix v3 notes\n\nbass is loud\n" + "\n".join(f"row {i}" for i in range(30)))
    (media / "spec.pdf").write_bytes(b"%PDF-1.4\nnot binary at all\n<< /Type /Pages /Kids [3 0 R] /Count 2 >>\n")
    m = intake.intake({"path": str(media / "notes.txt")}, [str(media)])["media"]
    assert m["head"][:2] == ["# mix v3 notes", "bass is loud"] and len(m["head"]) == 8
    assert sum(len(ln.encode()) + 1 for ln in m["head"]) <= 600
    p = intake.intake({"path": str(media / "spec.pdf")}, [str(media)])["media"]
    assert "head" not in p and p["pages"] == 2
    built = await build_card(event("agent.message", card_hint={"media": m}), "", detail=True)
    off = await build_card(event("agent.message", card_hint={"media": m}), "", detail=False)
    assert built.full["head"][0] == "# mix v3 notes" and "head" not in off.full


async def test_a_file_with_a_credential_is_refused_so_it_never_gets_a_head(media) -> None:
    (media / "env.txt").write_text(f"hello\nGITHUB_TOKEN={SECRET}\n")
    with pytest.raises(intake.IntakeError):
        intake.intake({"path": str(media / "env.txt")}, [str(media)])


async def test_signin_card_has_the_provider_and_the_sessions_measured_on_that_account(captured, monkeypatch) -> None:
    row = lambda state: SimpleNamespace(id="acct1", name="nyedis", provider="claude", credential_state=state, poke=None)  # noqa: E731
    watch = login.LoginWatch()
    watch.observe([row("ok")])
    watch.observe([row("refused")])
    infos = [SimpleNamespace(tmux_session="t_home"), SimpleNamespace(tmux_session="t_other"), SimpleNamespace(tmux_session="t_unmeasured")]

    async def list_infos() -> Any:
        return infos

    manager = SimpleNamespace(list_session_infos=list_infos, _label_for_tmux_name=lambda n: {"t_home": "home"}.get(n, n))
    from src.api import session_account_listing

    monkeypatch.setattr(session_account_listing, "cached_account", lambda i: {"t_home": "acct1", "t_other": "acct2"}.get(i.tmux_session))
    sources.install(LiveSources(SimpleNamespace(session_manager=manager)))
    try:
        built = await build_card(captured[0], "", detail=True)
    finally:
        sources.install(None)
    assert built.card["provider"] == "claude" and built.card["sessions"] == ["home"]


def test_one_retention_rule_drops_old_files_then_the_oldest_past_the_total(media, monkeypatch) -> None:
    old = store.write("file", b"old", "text/plain")
    new = store.write("file", b"new!", "text/plain")
    os.utime(store.media_dir() / f"{old.media_id}.bin", (1, 1))
    assert not hasattr(intake, "prune") and not hasattr(intake, "KEEP_SECONDS") and store.KEEP_SECONDS == 7 * 24 * 3600
    assert store.prune() == 1 and store.entry(old.media_id) is None and store.entry(new.media_id)
    monkeypatch.setattr(store, "TOTAL_MAX_BYTES", 1)
    assert store.prune() >= 1 and store.entry(new.media_id) is None


async def test_crosstalk_thread_is_that_sessions_last_three_agent_messages_oldest_first_and_details_off_drops_it() -> None:
    from src.core.sessions.toast_inbox import ToastInbox
    from src.models import Toast

    def toast(n: int, body: str, notify_type: str = "agent.message", session: str = "ses_1") -> Toast:
        return Toast(id=f"t{n}", session_id=session, kind="Notification", title="agent message", body=body, session_label="home",
                     notify_type=notify_type)

    inbox = ToastInbox()
    inbox.pending["ses_1"] = [toast(5, "x" * 400), toast(4, "stop here", "session.finished"), toast(3, "three"), toast(2, "two"), toast(1, "one")]
    inbox.pending["ses_2"] = [toast(9, "another session's", session="ses_2")]
    sources.install(LiveSources(SimpleNamespace(session_manager=SimpleNamespace(_toast_inbox=inbox))))
    try:
        ev = event("agent.message", kind="Notification", details="latest")
        on, off = await build_card(ev, "", detail=True), await build_card(ev, "", detail=False)
    finally:
        sources.install(None)
    thread = on.full["thread"]
    assert [t[1][:3] for t in thread] == ["two", "thr", "xxx"]
    assert thread[0][0] == "home" and len(thread[2][1]) <= 160 and all("another" not in t[1] for t in thread)
    assert "thread" not in off.full and "thread" not in off.card


async def test_more_is_set_when_the_full_card_holds_a_field_the_compact_card_lacks_and_the_swarm_item_stays_out_of_the_phone_payload() -> None:
    import sys

    sys.path.insert(0, "scripts/notify")
    import gen_contract  # noqa: PLC0415

    for kind in ("file", "crosstalk", "swarm"):
        assert gen_contract.sample_push(kind)["more"] is True, kind
    assert "more" not in gen_contract.sample_push("yesno") and gen_contract.sample_push("appupdate")["card"]["strip"][1] == ""
    ev = event("swarm.question_climbed", kind="Notification", card_hint={"ask": "which key signs the build?", "item": "526"})
    sources.install(LiveSources(SimpleNamespace()))
    try:
        built = await build_card(ev, "", detail=True)
        link = await build_card(event("agent.message", kind="Notification", card_hint={"url": "https://xn--bcher-kva.example/a"}), "", detail=True)
    finally:
        sources.install(None)
    assert built.kind == "swarm" and built.item == "526"
    assert "526" not in repr(built.card) + repr(built.full) + repr(built.acts) + repr(built.target)
    assert link.body.endswith(" \u00b7 xn--bcher-kva.example")
