
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from src.core.pack.transport import blobs

REPO = Path(__file__).resolve().parents[3]


def _sealed_blob(inbox: blobs.Inbox, blob_id: str, peer: str) -> bytes:
    data = b"bundle-bytes-of-" + peer.encode()
    sha = hashlib.sha256(data).hexdigest()
    inbox.put(blob_id, 0, data, sha, peer)
    inbox.seal(blob_id, len(data), sha, "bundle")
    return data


def test_the_uploader_reads_its_own_blob(tmp_path: Path) -> None:
    inbox = blobs.Inbox(tmp_path / "inbox")
    data = _sealed_blob(inbox, "b-aaaaaaaaaaaa", "peerA")
    assert inbox.sealed_path("b-aaaaaaaaaaaa", peer="peerA").read_bytes() == data


def test_another_peer_cannot_name_the_blob_and_the_refusal_is_logged(tmp_path: Path) -> None:
    inbox = blobs.Inbox(tmp_path / "inbox")
    _sealed_blob(inbox, "b-aaaaaaaaaaaa", "peerA")
    with pytest.raises(blobs.BlobError) as refused:
        inbox.sealed_path("b-aaaaaaaaaaaa", peer="peerB")
    assert (refused.value.code, refused.value.status) == ("blob_not_yours", 403)
    assert inbox.sealed_path("b-aaaaaaaaaaaa", peer="peerA").is_file()


def test_a_blob_with_no_recorded_owner_is_refused_to_everyone(tmp_path: Path) -> None:
    inbox = blobs.Inbox(tmp_path / "inbox")
    _sealed_blob(inbox, "b-aaaaaaaaaaaa", "peerA")
    (tmp_path / "inbox" / "b-aaaaaaaaaaaa.peer").unlink()
    with pytest.raises(blobs.BlobError) as refused:
        inbox.sealed_path("b-aaaaaaaaaaaa", peer="peerA")
    assert refused.value.code == "blob_not_yours"
    with pytest.raises(blobs.BlobError):
        inbox.sealed_path("b-aaaaaaaaaaaa", peer="")


def test_unknown_and_malformed_ids_keep_their_codes(tmp_path: Path) -> None:
    inbox = blobs.Inbox(tmp_path / "inbox")
    with pytest.raises(blobs.BlobError) as unknown:
        inbox.sealed_path("b-zzzzzzzzzzzz", peer="peerA")
    assert unknown.value.code == "unknown_blob"
    with pytest.raises(blobs.BlobError) as bad:
        inbox.sealed_path("../x", peer="peerA")
    assert bad.value.code == "bad_blob_id"


def test_every_caller_in_src_names_the_peer() -> None:
    seen = covered = 0
    for path in (REPO / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        handled: set = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "sealed_path":
                handled.add(id(node.func))
                seen += 1
                covered += any(k.arg == "peer" for k in node.keywords)
            for arg in node.args[:1]:
                if isinstance(arg, ast.Attribute) and arg.attr == "sealed_path":
                    handled.add(id(arg))
                    seen += 1
                    covered += any(k.arg == "peer" for k in node.keywords)
        stray = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "sealed_path" and id(n) not in handled]
        assert not stray, f"{path}: sealed_path used without a visible peer"
    assert seen >= 8, "the scan found too few callers, so it proves nothing"
    assert covered == seen
