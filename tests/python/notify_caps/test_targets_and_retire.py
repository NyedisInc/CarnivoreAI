
from __future__ import annotations

import ast
import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import pytest  # noqa: E402

from src.core.approvals.inbox import item_id  # noqa: E402
from src.core.notify_caps import act as act_mod  # noqa: E402
from src.core.notify_caps import effects, retire  # noqa: E402
from src.core.notify_caps import store as store_mod  # noqa: E402
from src.core.notify_caps import verify as verify_mod  # noqa: E402
from src.plugins.sdk.owner_reply import NAME as OWNER_REPLY_PORT, OwnerReplyDeclined  # noqa: E402
from src.plugins.sdk import ports  # noqa: E402

CARDS = Path(__file__).resolve().parents[3] / "src" / "core" / "notifications" / "cards"
FP = "c" * 64
CLIENT_ONLY_TARGETS = {"media", "none"}


def minted_targets() -> set:
    found = set()
    for name in ("builders.py", "payload.py"):
        for node in ast.walk(ast.parse((CARDS / name).read_text())):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "type" and isinstance(v, ast.Constant) and isinstance(v.value, str):
                        found.add(v.value)
            elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_session_target":
                found.add(node.args[1].value)
            elif isinstance(node, ast.IfExp) and name == "payload.py":
                found |= {n.value for n in (node.body, node.orelse) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return found


def test_every_minted_target_has_an_effect():
    targets = minted_targets()
    assert {"dialog", "send", "reopen", "swarm", "app_update", "agent_update"} <= targets
    effective = set(act_mod.EFFECT_ACTIONS) | {"dialog"}
    missing = targets - effective - CLIENT_ONLY_TARGETS
    assert not missing, f"targets with no effect: {missing}"
    assert not hasattr(act_mod, "PENDING_TARGETS")


def test_update_card_offers_restart_and_stores_the_session_ids():
    from src.core.notifications.cards import builders
    from src.core.notifications.cards.model import Ctx
    ctx = Ctx(SimpleNamespace(), None, {"from": "2.1.301", "to": "2.1.312", "sessions": ["a"], "ids": ["ses_1"]}, "claude code", "nostromo", True, "update")
    part = builders.update(ctx)
    assert [a[0] for a in part.acts] == ["restart_agents", "later"]
    assert part.target == {"type": "agent_update", "sessions": ["ses_1"]}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "db_path", lambda: tmp_path / "notify_caps.db")
    monkeypatch.setattr(act_mod, "watcher_of", lambda _m: None)
    state = SimpleNamespace(session_manager=None, native_device_store=SimpleNamespace(list=lambda: [{"id": "d1"}]))
    return state


def mint(target, actions, card=None):
    return store_mod.get_store().mint(device_row_id="d1", type_id="t", kind="swarm", target=target, actions=actions,
                                      card=card or {}, ask=True)[0]


def press(state, cap, action, text=None):
    return asyncio.run(act_mod.act(store_mod.get_store(), state, cap, action, text))


def offer_owner_reply(monkeypatch, fn):
    class Port:
        owner_reply = staticmethod(fn)

    monkeypatch.setitem(ports._ports, OWNER_REPLY_PORT, Port())


SWARM_ACTIONS = {"pick.1": "pick a", "pick.2": "pick b", "answer": "answer"}
POSITIONS = {"positions": [["a", "use sqlite"], ["b", "use postgres"]]}


def test_swarm_pick_answers_with_the_stored_position_through_the_huddle_reply(rig, monkeypatch):
    seen = []

    async def item(_q):
        return 526

    async def reply(_state, item_id_, text):
        seen.append((item_id_, text))
        return {}

    monkeypatch.setattr(effects, "swarm_card_item", item)
    offer_owner_reply(monkeypatch, reply)
    cap = mint({"type": "swarm", "question": "7"}, SWARM_ACTIONS, POSITIONS)
    assert press(rig, cap, "pick.2")[0] == 200
    assert seen == [(526, "use postgres")]
    cap2 = mint({"type": "swarm", "question": "7"}, SWARM_ACTIONS, POSITIONS)
    assert press(rig, cap2, "answer", "neither, ask Joe")[0] == 200
    assert seen[-1] == (526, "neither, ask Joe")
    assert press(rig, mint({"type": "swarm", "question": "7"}, SWARM_ACTIONS, POSITIONS), "answer")[0] == 422


def test_swarm_question_not_open_is_409(rig, monkeypatch):
    async def none(_q):
        return None

    monkeypatch.setattr(effects, "swarm_card_item", none)
    status, body = press(rig, mint({"type": "swarm", "question": "7"}, SWARM_ACTIONS, POSITIONS), "pick.1")
    assert (status, body["error"]) == (409, "already_answered")


def test_swarm_refusal_from_the_swarm_is_409_and_nothing_logged(rig, monkeypatch, caplog):
    async def item(_q):
        return 526

    async def refuse(*_a):
        raise OwnerReplyDeclined("that question is not waiting for the owner")

    monkeypatch.setattr(effects, "swarm_card_item", item)
    offer_owner_reply(monkeypatch, refuse)
    with caplog.at_level("DEBUG"):
        cap = mint({"type": "swarm", "question": "7"}, SWARM_ACTIONS, POSITIONS)
        assert press(rig, cap, "answer", "SECRETANSWER")[0] == 409
    assert "SECRETANSWER" not in caplog.text and cap not in caplog.text


def test_resolved_ask_retires_its_capabilities_and_a_repeat_prompt_is_not_answered_by_the_old_one(rig):
    target = {"type": "dialog", "session": "ses_1", "fingerprint": FP}
    old = mint(target, {"yes": "Yes"})
    other_ask = mint({"type": "dialog", "session": "ses_2", "fingerprint": FP}, {"yes": "Yes"})
    retire.on_lost([("dialog", item_id("ses_1", FP))])
    record, refused = verify_mod.verify(store_mod.get_store(), rig, old)
    assert record is None and refused[0] == 409 and refused[1]["error"] == "already_answered"
    assert press(rig, old, "yes")[0] == 409
    fresh = mint(target, {"yes": "Yes"})
    assert verify_mod.verify(store_mod.get_store(), rig, fresh)[0] is not None
    assert verify_mod.verify(store_mod.get_store(), rig, other_ask)[0] is not None


def test_an_old_database_gains_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE caps (cap_sha256 TEXT PRIMARY KEY, device_row_id TEXT NOT NULL, type_id TEXT NOT NULL, kind TEXT NOT NULL,"
                 " target TEXT NOT NULL, actions TEXT NOT NULL, media_ids TEXT NOT NULL, card_json TEXT NOT NULL, created REAL NOT NULL,"
                 " expires REAL NOT NULL, used_at REAL, used_action TEXT, result_json TEXT)")
    conn.commit()
    conn.close()
    store = store_mod.CapStore(path)
    cap, _ = store.mint(device_row_id="d1", type_id="t", kind="k", target={"type": "dialog", "session": "s", "fingerprint": FP}, actions={})
    assert store.find(cap).ask_id == item_id("s", FP)
