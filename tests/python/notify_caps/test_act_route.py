
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import pytest  # noqa: E402
import structlog  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.core.approvals.answer import AnswerRefused  # noqa: E402
from src.core.attention.evidence import STATE_BUSY, STATE_DONE_IDLE  # noqa: E402
from src.core.notify_caps import act as act_mod  # noqa: E402
from src.core.notify_caps import store as store_mod  # noqa: E402
from src.core.notify_caps import verify as verify_mod  # noqa: E402
from src.core.notify_caps.limiter import LIMITER  # noqa: E402
from src.core.notify_media import store as media_mod  # noqa: E402
from src.core.phone_link import gate  # noqa: E402
from src.main import app  # noqa: E402

FP = "a" * 64
URL = "/api/v1/notify/act"


class Watcher:

    def __init__(self) -> None:
        self.rev, self.state, self.bump = 1, STATE_BUSY, True

    def observation_for(self, _sid):
        return SimpleNamespace(revision=self.rev, stale=False, verdict=SimpleNamespace(state=self.state))


class Manager:
    def __init__(self, watcher) -> None:
        self._attention_watcher = watcher
        self.info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), label="api-docs", tmux_session="carnivore_x")

    async def get_session_info(self, sid):
        return self.info if sid == "ses_1" else None


rig_extra: dict = {}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "db_path", lambda: tmp_path / "notify_caps.db")
    monkeypatch.setattr(media_mod, "media_dir", lambda: tmp_path)
    LIMITER._misses.clear()
    watcher = Watcher()
    calls = []

    async def fake_deliver(**kw):
        calls.append(kw)
        if kw["fingerprint"] == "gone":
            raise AnswerRefused("dialog_changed")
        watcher.rev += 1

    monkeypatch.setattr(act_mod, "deliver_answer", fake_deliver)
    paired = [{"id": "d1"}]
    app.state.native_device_store = SimpleNamespace(list=lambda: list(paired))
    verdict = ["open"]

    async def fake_verdict(_app, _sid):
        return verdict[0]

    monkeypatch.setattr(verify_mod, "dialog_verdict", fake_verdict)
    monkeypatch.setattr(act_mod, "SETTLE_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(act_mod, "SETTLE_POLL_SECONDS", 0.05)
    app.state.session_manager = Manager(watcher)

    def mint(fp=FP, actions=None, **kw):
        return store_mod.get_store().mint(
            device_row_id="d1", type_id="session.question", kind="choice",
            target={"type": "dialog", "session": "ses_1", "fingerprint": fp},
            actions=actions or {"yes": "Yes", "no": "No", "opt.2": "Blue", "reply": "reply"},
            card={"agent": "api-docs", "ask": "pick"}, ask=True, **kw)

    rig_extra.update(paired=paired, verdict=verdict)
    yield TestClient(app), mint, calls, watcher
    del app.state.session_manager
    del app.state.native_device_store


def hdr(cap):
    return {store_mod.HEADER_NAME: cap}


def test_act_route_end_to_end(rig, caplog, tmp_path):
    client, mint, calls, watcher = rig
    with structlog.testing.capture_logs() as captured:
        cap, _ = mint()
        first = client.post(URL, headers=hdr(cap), json={"action": "opt.2"})
        assert first.status_code == 200 and first.json() == {"state": "sent", "agent": "api-docs", "working": True}
        assert len(calls) == 1 and calls[0]["source"] == "owner_phone" and calls[0]["choice"].option == "Blue"
        assert calls[0]["fingerprint"] == FP
        again = client.post(URL, headers=hdr(cap), json={"action": "opt.2"})
        assert again.status_code == 200 and again.json()["replay"] is True and len(calls) == 1
        other = client.post(URL, headers=hdr(cap), json={"action": "yes"})
        assert other.status_code == 409 and other.json() == {"error": "already_used"}
        assert cap.encode() not in (tmp_path / "notify_caps.db").read_bytes()
        assert oct((tmp_path / "notify_caps.db").stat().st_mode & 0o777) == "0o600"

        watcher.state = STATE_DONE_IDLE
        cap2, _ = mint()
        assert client.post(URL, headers=hdr(cap2), json={"action": "no"}).json()["working"] is False
        cap3, _ = mint()
        watcher.bump = False
        real = watcher.observation_for
        watcher.observation_for = lambda sid: SimpleNamespace(revision=0, stale=False, verdict=SimpleNamespace(state=STATE_BUSY))
        assert client.post(URL, headers=hdr(cap3), json={"action": "yes"}).json()["working"] is False
        watcher.observation_for = real

        cap4, _ = mint(fp="gone")
        gone = client.post(URL, headers=hdr(cap4), json={"action": "yes"})
        assert gone.status_code == 409 and gone.json() == {"error": "already_answered", "where": "elsewhere"}
        assert client.post(URL, headers=hdr(cap4), json={"action": "yes"}).status_code == 409

        cap5, _ = mint()
        for body in ({"action": "approve_all"}, {"action": "reply"}, {"action": "yes", "extra": 1}):
            assert client.post(URL, headers=hdr(cap5), json=body).status_code == 422
        assert client.post(URL, headers=hdr(cap5), json={"action": "reply", "text": "use blue"}).status_code == 200
        assert calls[-1]["choice"].other == "use blue"

        cap6, _ = mint(now=1.0)
        assert client.post(URL, headers=hdr(cap6), json={"action": "yes"}).status_code == 410
        assert client.get("/api/v1/notify/card", headers=hdr(cap6)).status_code == 410

        assert client.get("/api/v1/notify/card", headers=hdr(cap5)).json() == {"agent": "api-docs", "ask": "pick"}

        for bad in ("A" * 43, "short", ""):
            r = client.post(URL, headers=hdr(bad) if bad else {}, json={"action": "yes"})
            assert r.status_code == 404 and r.json() == {"error": "not_found"}
        for _ in range(7):
            assert client.get("/api/v1/notify/card", headers=hdr("B" * 43)).status_code == 404
        assert client.get("/api/v1/notify/card", headers=hdr("E" * 43)).status_code == 429
        good, _ = mint()
        assert client.post(URL, headers=hdr(good), json={"action": "yes"}).status_code == 200

    secrets_seen = [cap, cap2, cap3, cap4, cap5, cap6, good]
    text = caplog.text + repr(captured)
    assert not any(c in text for c in secrets_seen)
    assert "notify_cap_acted" in text


def test_media_needs_its_capability_and_serves_range(rig):
    client, mint, _, _ = rig
    entry = media_mod.write("video", b"0123456789", "video/mp4", poster=b"\x89PNG")
    cap, _ = mint(media_ids=[entry.media_id])
    other, _ = mint()
    url = f"/api/v1/notify/media/{entry.media_id}"
    assert client.get(url, headers=hdr(cap)).content == b"0123456789"
    assert client.get(url, headers=hdr(cap) | {"Range": "bytes=2-4"}).content == b"234"
    assert client.get(url + "/poster", headers=hdr(cap)).headers["content-type"] == "image/png"
    assert client.get(url, headers=hdr(other)).status_code == 404
    assert client.get(url).status_code == 404
    with pytest.raises(ValueError):
        media_mod.write("image", b"x" * (10 * 2**20 + 1), "image/png")


def test_gate_passes_exactly_the_capability_routes():
    mid = "f" * 32
    yes = [("POST", "/api/v1/notify/act"), ("GET", "/api/v1/notify/card"),
           ("GET", f"/api/v1/notify/media/{mid}"), ("GET", f"/api/v1/notify/media/{mid}/poster")]
    no = [("GET", "/api/v1/notify/act"), ("POST", "/api/v1/notify/card"), ("POST", f"/api/v1/notify/media/{mid}"),
          ("GET", "/api/v1/notify/act/"), ("GET", "/API/v1/notify/card"), ("GET", "/api/v1/notify/media/../act"),
          ("GET", f"/api/v1/notify/media/{mid}/x"), ("GET", "/api/v1/notify/media/short"), ("GET", "/api/v1/notify"),
          ("GET", "/api/v1/notify/card/x"), ("GET", "/api/v1/notify/destinations")]
    assert all(gate.is_cap_route(m, p) for m, p in yes)
    assert not any(gate.is_cap_route(m, p) for m, p in no)


def test_m1_a_fault_in_the_settle_wait_replays_instead_of_pressing_again(rig, monkeypatch):
    client, mint, calls, _ = rig
    cap, _ = mint()

    async def boom(*_a, **_k):
        raise RuntimeError("restart during the settle wait")

    real_wait = act_mod._working_after
    monkeypatch.setattr(act_mod, "_working_after", boom)
    with pytest.raises(RuntimeError):
        client.post(URL, headers=hdr(cap), json={"action": "yes"})
    assert len(calls) == 1
    monkeypatch.setattr(act_mod, "_working_after", real_wait)
    retry = client.post(URL, headers=hdr(cap), json={"action": "yes"})
    assert retry.status_code == 200 and retry.json()["replay"] is True and retry.json()["state"] == "sent"


def test_m2_an_unpaired_phones_capability_is_not_found(rig):
    client, mint, calls, _ = rig
    cap, _ = mint()
    rig_extra["paired"].clear()
    assert client.post(URL, headers=hdr(cap), json={"action": "yes"}).status_code == 404
    assert client.get("/api/v1/notify/card", headers=hdr(cap)).status_code == 404
    assert calls == []


def test_l1_a_resolved_ask_refuses_acts_but_still_serves_the_card(rig):
    client, mint, calls, _ = rig
    cap, _ = mint()
    rig_extra["verdict"][0] = "clear"
    r = client.post(URL, headers=hdr(cap), json={"action": "yes"})
    assert r.status_code == 409 and r.json()["error"] == "already_answered" and calls == []
    assert client.get("/api/v1/notify/card", headers=hdr(cap)).status_code == 200


def test_l3_a_refusal_that_changed_nothing_gives_the_capability_back(rig, monkeypatch):
    client, mint, calls, _ = rig

    async def refuse(**_kw):
        raise AnswerRefused("cursor_unreadable")

    cap, _ = mint()
    monkeypatch.setattr(act_mod, "deliver_answer", refuse)
    r = client.post(URL, headers=hdr(cap), json={"action": "yes"})
    assert r.status_code == 409 and r.json() == {"error": "refused", "reason": "cursor_unreadable"}
    assert store_mod.get_store().find(cap).used_at is None


def test_l4_a_second_reply_with_other_text_is_409_and_the_same_text_replays(rig):
    client, mint, calls, _ = rig
    cap, _ = mint()
    assert client.post(URL, headers=hdr(cap), json={"action": "reply", "text": "use blue"}).status_code == 200
    again = client.post(URL, headers=hdr(cap), json={"action": "reply", "text": "use blue"})
    assert again.status_code == 200 and again.json()["replay"] is True
    other = client.post(URL, headers=hdr(cap), json={"action": "reply", "text": "no, red"})
    assert other.status_code == 409 and other.json() == {"error": "already_used"} and len(calls) == 1


def test_l5_an_oversized_body_is_413_before_it_is_parsed(rig):
    client, mint, calls, _ = rig
    cap, _ = mint()
    r = client.post(URL, headers=hdr(cap), content=b"x" * 100_000)
    assert r.status_code == 413 and calls == []


def test_media_is_served_as_an_attachment_and_stored_private(rig, monkeypatch, tmp_path):
    client, mint, _, _ = rig
    root = tmp_path / "media"
    monkeypatch.setattr(media_mod, "media_dir", lambda: (root.mkdir(mode=0o700, exist_ok=True), root.chmod(0o700), root)[2])
    entry = media_mod.write("image", b"abc", "image/png")
    cap, _ = mint(media_ids=[entry.media_id])
    r = client.get(f"/api/v1/notify/media/{entry.media_id}", headers=hdr(cap))
    assert r.headers["content-disposition"].startswith("attachment")
    assert oct(root.stat().st_mode & 0o777) == "0o700" and oct(entry.path.stat().st_mode & 0o777) == "0o600"
