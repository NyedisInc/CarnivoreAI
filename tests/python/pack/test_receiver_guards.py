
import hashlib
import io
import os
import subprocess
import tarfile

import pytest

from src.core.pack.transport import blobs, tarball

pytestmark = pytest.mark.skipif(subprocess.run(["which", "zstd"], capture_output=True).returncode != 0 and not os.path.exists("/opt/homebrew/bin/zstd"), reason="zstd missing")


def _archive(tmp_path, build) -> str:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        build(tar)
    path = tmp_path / "a.tar.zst"
    out = subprocess.run([tarball._zstd(), "-q", "-c"], input=raw.getvalue(), capture_output=True, check=True)
    path.write_bytes(out.stdout)
    return str(path)


def _file(tar, name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _special(tar, name, kind, link=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    tar.addfile(info)


def _refused(tmp_path, build, **kw):
    dest = tmp_path / "dest"
    with pytest.raises(tarball.TarballError) as exc:
        tarball.extract_tarball(_archive(tmp_path, build), str(dest), **kw)
    assert exc.value.code == "unsafe_archive"
    assert not dest.exists()


def test_plain_archive_extracts(tmp_path):
    def build(tar):
        _file(tar, "src/a.txt", b"hello")
        _special(tar, "ok-link", tarfile.SYMTYPE, "src/a.txt")
    dest = tmp_path / "dest"
    assert tarball.extract_tarball(_archive(tmp_path, build), str(dest), max_bytes=1_000_000) == 2
    assert (dest / "src" / "a.txt").read_bytes() == b"hello"


@pytest.mark.parametrize("name", [".git/config", ".GIT/config", "sub/.git", "sub/.Git/hooks/post-merge", ".gitmodules", "./.gitmodules",
                                  ".git.", ".git ", ".GIT..", "sub/.git. .", ".gitmodules.", ".GitModules ", "./.gitmodules. "])
def test_git_control_paths_refused(tmp_path, name):
    _refused(tmp_path, lambda tar: _file(tar, name, b"[core]\n\tfsmonitor = touch /tmp/pwned\n"), max_bytes=1_000_000)


def test_symlink_out_of_root_refused(tmp_path):
    _refused(tmp_path, lambda tar: _special(tar, "evil", tarfile.SYMTYPE, "../../etc"), max_bytes=1_000_000)
    _refused(tmp_path, lambda tar: _special(tar, "evil", tarfile.SYMTYPE, "/etc"), max_bytes=1_000_000)


def test_hardlink_and_special_members_refused(tmp_path):
    def build(tar):
        _file(tar, "a", b"x")
        _special(tar, "b", tarfile.LNKTYPE, "a")
    _refused(tmp_path, build, max_bytes=1_000_000)
    _refused(tmp_path, lambda tar: _special(tar, "fifo", tarfile.FIFOTYPE), max_bytes=1_000_000)


def test_zstd_bomb_past_ceiling_refused(tmp_path):
    _refused(tmp_path, lambda tar: _file(tar, "big", b"\0" * 5_000_000), max_bytes=1_000_000)


def test_member_count_over_cap_refused(tmp_path):
    def build(tar):
        for i in range(6):
            _file(tar, f"f{i}", b"x")
    _refused(tmp_path, build, max_bytes=1_000_000, max_members=5)


def _put(inbox, blob_id, data, peer):
    return inbox.put(blob_id, 0, data, hashlib.sha256(data).hexdigest(), peer)


def test_inbox_quotas(tmp_path, monkeypatch):
    monkeypatch.setattr(blobs, "MAX_PEER_INBOX_BYTES", 10)
    monkeypatch.setattr(blobs, "MAX_TOTAL_INBOX_BYTES", 15)
    inbox = blobs.Inbox(tmp_path / "inbox")
    _put(inbox, "b-aaaaaaaaaaaa", b"12345678", "peerA")
    with pytest.raises(blobs.BlobError) as peer:
        _put(inbox, "b-bbbbbbbbbbbb", b"123", "peerA")
    assert (peer.value.code, peer.value.status) == ("inbox_quota_peer", 507)
    _put(inbox, "b-cccccccccccc", b"12345", "peerB")
    with pytest.raises(blobs.BlobError) as total:
        _put(inbox, "b-dddddddddddd", b"12345", "peerC")
    assert total.value.code == "inbox_quota_total"
