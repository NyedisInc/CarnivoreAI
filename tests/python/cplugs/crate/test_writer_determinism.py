
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request

EPOCH = 1792267200


def _forget_exports(state: Path) -> None:
    with closing(connect(db_path_for(state))) as conn:
        conn.execute("DELETE FROM export_pointers")
        conn.execute("DELETE FROM export_bundles")
        conn.commit()


@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_two_exports_are_byte_identical(tmp_path: Path, codec: str) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    outputs = []
    for index in range(2):
        _forget_exports(Path(w.state))
        result = run_export(env, build_plan(env, project_request(w)), JobHandle(str(index)), codec=codec,
                            created_epoch=EPOCH, bundle_id=f"crate-golden-{index}")
        data = result.path.read_bytes()
        outputs.append((result, data.replace(f"crate-golden-{index}".encode(), b"crate-golden-X")))
        os.rename(result.path, result.path.with_suffix(".done"))
    (first, a), (second, b) = outputs
    assert first.content_id == second.content_id
    assert a == b
