
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.crate import copying as copying_module
from src.cplugs.crate import publish as publish_module
from src.cplugs.crate.copying import CopyFailed, copy_crate
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return make_world(tmp_path)


def _left(folder: Path) -> list:
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_a_failed_rename_after_the_reservation_leaves_no_empty_crate(world: SimpleNamespace,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(src, dst):
        raise PermissionError(1, "Operation not permitted")

    def flaky_rename(src, dst):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(publish_module.os, "link", no_links)
    monkeypatch.setattr(publish_module.os, "rename", flaky_rename)
    env = env_for(world)
    with pytest.raises(OSError, match="Input/output"):
        run_export(env, build_plan(env, session_request()), JobHandle("r"))
    assert _left(Path(world.state) / "crates") == []


def test_an_fsync_error_after_a_good_link_leaves_no_crate(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_fsync(folder: Path) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(publish_module, "fsync_dir", broken_fsync)
    env = env_for(world)
    with pytest.raises(OSError, match="Input/output"):
        run_export(env, build_plan(env, session_request()), JobHandle("f"))
    assert _left(Path(world.state) / "crates") == []


def test_publish_never_removes_a_name_it_did_not_create(tmp_path: Path) -> None:
    temp, final = tmp_path / ".x.partial", tmp_path / "x.crate"
    temp.write_bytes(b"ours")
    final.write_bytes(b"theirs")
    with pytest.raises(publish_module.NameTaken):
        publish_module.publish(temp, final)
    assert final.read_bytes() == b"theirs" and temp.read_bytes() == b"ours"


def test_a_copy_whose_sidecar_fails_leaves_nothing_in_the_second_folder(world: SimpleNamespace, tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    env = env_for(world)
    result = run_export(env, build_plan(env, session_request()), JobHandle("c"))
    second = tmp_path / "second"
    second.mkdir()

    def broken_sidecar(final: Path, data: bytes, on_temp=None) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(copying_module, "write_new", broken_sidecar)
    sha = hashlib.sha256(result.path.read_bytes()).hexdigest()
    with pytest.raises(CopyFailed) as caught:
        copy_crate(result.path, second, sha, JobHandle("c2"), sidecars=[(f"{result.file_name}.sha256", b"x")])
    assert caught.value.code == "copy_failed" and _left(second) == []
    assert os.path.isfile(result.path)
