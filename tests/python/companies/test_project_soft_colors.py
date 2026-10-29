
from __future__ import annotations

import re
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.project_colors.palette import SOFT_PALETTE, is_hex_color, normalize_color
from src.core.project_writes import ProjectColorInvalid, create_project, update_project

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def conn(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as c:
        run_chain(c, 0, CURRENT_SCHEMA_VERSION)
        yield c


def test_update_accepts_any_hex_and_refuses_the_rest(conn, tmp_path):
    (tmp_path / "a").mkdir()
    pid = create_project(conn, name="a", path=str(tmp_path / "a"))["id"]
    assert update_project(conn, pid, color="#AABBCC")["color"] == "#aabbcc"
    assert update_project(conn, pid, color="")["color"] is None
    assert update_project(conn, pid, color=None)["color"] is None
    for bad in ("pink", "cyan", "orange", "green-bright", "#abc", "red", "#gggggg"):
        with pytest.raises(ProjectColorInvalid):
            update_project(conn, pid, color=bad)
    assert is_hex_color("#c17b87") and normalize_color("#C17B87") == "#c17b87"


def test_the_web_soft_palette_matches_the_server():
    source = (ROOT / "web/src/lib/project-colors/palette.ts").read_text()
    block = source.split("SOFT_PROJECT_COLORS")[1].split("] as const")[0]
    assert tuple(re.findall(r"'(#[0-9a-f]{6})'", block)) == SOFT_PALETTE
