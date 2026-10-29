
from __future__ import annotations

from src.core.approvals import peer_items
from src.core.federation.peer_hosts import PeerRow
from src.models.dialogs import ApprovalItem

PEER = PeerRow(key="peer-a", label="a", ssh_target="a", ssh_port=None, peer_install_id="iid-a", peer_grant_id="g", peer_fid="f",
               peer_protocol=1, peer_state="up", initiator=True, peer_port=None, back_kind="x")
RAW = {"id": "d1", "source": "dialog", "host": "local", "session_id": "ses_1", "tmux_session": "carnivore_x", "kind": "ask_user_question",
       "origin_install_id": "iid-a", "fingerprint": "f" * 64, "questions_state": "matched", "questions_fingerprint": "q" * 64,
       "questions": [{"header": "H", "question": "Pick?", "multi_select": False, "options": [{"label": "A"}]}]}


def test_an_imported_ask_keeps_its_questions_and_fingerprint_and_names_the_remote_session():
    item = peer_items.accept(RAW, PEER)
    assert isinstance(item, ApprovalItem)
    assert item.questions == RAW["questions"] and item.questions_fingerprint == "q" * 64 and item.questions_state == "matched"
    assert item.host == "peer-a" and item.session_id.startswith("remote:peer-a:")


def test_an_older_peer_item_without_questions_stays_a_plain_dialog_item():
    old = {k: v for k, v in RAW.items() if not k.startswith("questions")}
    item = peer_items.accept(old, PEER)
    assert item is not None and item.questions == [] and item.questions_state is None and item.questions_fingerprint is None


class _Links:

    def __init__(self, minor: int) -> None:
        self._minor = minor

    def client(self, _iid):
        return self

    async def request(self, _method, _path):
        from types import SimpleNamespace
        return SimpleNamespace(status_code=200, json=lambda: {"items": [RAW]})

    def minor(self, _iid) -> int:
        return self._minor


def test_a_peer_below_the_batch_minor_is_listed_without_questions_so_no_submit_is_offered():
    import asyncio
    from src.core.federation.pairing import ANSWER_ALL_MINOR
    old = asyncio.run(peer_items._one(PEER, _Links(ANSWER_ALL_MINOR - 1)))[0]
    assert old["questions"] == [] and old["questions_state"] is None and old["questions_fingerprint"] is None
    assert old["kind"] == "ask_user_question" and old["fingerprint"] == "f" * 64
    new = asyncio.run(peer_items._one(PEER, _Links(ANSWER_ALL_MINOR)))[0]
    assert new["questions_state"] == "matched" and len(new["questions"]) == 1


def test_a_peer_item_carries_the_paired_computers_name():
    item = peer_items.accept(RAW, PEER)
    assert item is not None and item.host_label == PEER.label and item.host == PEER.key
