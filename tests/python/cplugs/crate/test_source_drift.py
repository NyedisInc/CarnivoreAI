
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.cplugs.crate import write_files, writer as writer_module
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.source_read import SourceUnstable
from src.cplugs.crate.writer import ExportFailed, run_export
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request
from tests.python.inventory.world import CONV_A


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    w.transcript = Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A}.jsonl"
    w.seeded = _count(w)
    return w


def _count(w: SimpleNamespace) -> int:
    with closing(connect(db_path_for(w.state))) as conn:
        return conn.execute("SELECT count(*) FROM export_bundles").fetchone()[0]


def _nothing_left(w: SimpleNamespace) -> bool:
    folder = Path(w.state) / "crates"
    return _count(w) == w.seeded and (not folder.is_dir() or not any(folder.iterdir()))


def test_an_append_during_the_read_is_source_unstable(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    real = write_files.disk_chunks

    def appending(fd, st, line_mode, path=""):
        for index, chunk in enumerate(real(fd, st, line_mode, path)):
            if index == 0 and path == str(world.transcript):
                with open(path, "a") as handle:
                    handle.write('{"late":1}\n')
            yield chunk

    monkeypatch.setattr(write_files, "disk_chunks", appending)
    env = env_for(world)
    with pytest.raises(SourceUnstable) as caught:
        run_export(env, build_plan(env, session_request()), JobHandle("a"))
    assert caught.value.path == str(world.transcript) and _nothing_left(world)


def test_a_change_after_the_crate_is_closed_is_source_changed(world: SimpleNamespace,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    real = writer_module.cf.verify

    def changing(path, *args, **kwargs):
        report = real(path, *args, **kwargs)
        data = world.transcript.read_bytes()
        world.transcript.write_bytes(data.replace(b"transcript", b"Transcript"))
        return report

    monkeypatch.setattr(writer_module.cf, "verify", changing)
    env = env_for(world)
    with pytest.raises(ExportFailed) as caught:
        run_export(env, build_plan(env, session_request()), JobHandle("b"))
    assert caught.value.code == "source_changed" and str(world.transcript) in caught.value.detail
    assert _nothing_left(world)
