
import os
import tarfile
import subprocess

import pytest

from src.core.pack.transport import ladder, tarball
from tests.python.pack.test_receiver_guards import _archive, _file, _special

pytestmark = pytest.mark.skipif(subprocess.run(["which", "zstd"], capture_output=True).returncode != 0 and not os.path.exists("/opt/homebrew/bin/zstd"), reason="zstd missing")


def _extract_refused(tmp_path, build):
    parent = tmp_path / "proj"
    parent.mkdir()
    (parent / "SIBLING_SECRET").write_text("outside\n")
    with pytest.raises(tarball.TarballError) as exc:
        tarball.extract_tarball(_archive(tmp_path, build), str(parent / "root"), max_bytes=10_000_000)
    assert exc.value.code == "unsafe_archive"
    assert not (parent / "root").exists()
    return parent


def _strays(tmp_path):
    return [p.name for p in tmp_path.rglob("PWNED")]


def test_long_symlink_chain_escape_refused(tmp_path):
    comp, steps = "d" * 55, "abcdefghijklmnop"

    def build(tar):
        walk = ""
        for s in steps:
            info = tarfile_dir(os.path.join(walk, comp))
            tar.addfile(info)
            _special(tar, os.path.join(walk, s), tarfile.SYMTYPE, comp)
            walk = os.path.join(walk, s)
        link = os.path.join("/".join(steps), "l" * 254)
        _special(tar, link, tarfile.SYMTYPE, "../" * len(steps))
        _special(tar, "escape", tarfile.SYMTYPE, link + "/.." * 3)
        _file(tar, "escape/PWNED", b"written by a peer\n")
    _extract_refused(tmp_path, build)
    assert _strays(tmp_path) == []


def tarfile_dir(name):
    info = tarfile.TarInfo(name)
    info.type, info.mode = tarfile.DIRTYPE, 0o755
    return info


def test_dotdot_inside_link_target_refused(tmp_path):
    def build(tar):
        _special(tar, "./s1", tarfile.SYMTYPE, "s2/x/../..")
        _special(tar, "./s2", tarfile.SYMTYPE, ".")
        _file(tar, "./x/keep", b"k")
        _file(tar, "s1/PWNED", b"p")
    parent = _extract_refused(tmp_path, build)
    assert _strays(tmp_path) == [] and (parent / "SIBLING_SECRET").read_text() == "outside\n"


def test_write_through_an_earlier_link_refused(tmp_path):
    def build(tar):
        tar.addfile(tarfile_dir("sub"))
        _special(tar, "ln", tarfile.SYMTYPE, "sub")
        _file(tar, "ln/PWNED", b"p")
    _extract_refused(tmp_path, build)
    assert _strays(tmp_path) == []


def test_link_member_replacing_nothing_is_still_allowed(tmp_path):
    dest = tmp_path / "dest"
    assert tarball.extract_tarball(_archive(tmp_path, lambda t: (_file(t, "a.txt"), _special(t, "ok", tarfile.SYMTYPE, "a.txt"))), str(dest), max_bytes=1_000_000) == 2


@pytest.mark.parametrize("url,flag", [("https://u:tok@github.com/o/r.git", True), ("https://tok@github.com/o/r", True), ("git@github.com:o/r.git", False),
                                      ("ssh://git@github.com/o/r.git", False), ("https://github.com/o/r.git", False)])
def test_remote_userinfo_detected(url, flag):
    assert ladder.remote_has_userinfo(url) is flag


def test_clone_refuses_a_url_with_a_login():
    with pytest.raises(RuntimeError, match="clone_failed"):
        ladder.clone_from_origin("https://u:tok@github.com/o/r.git", "/nonexistent/x", [], air_gap=False)
