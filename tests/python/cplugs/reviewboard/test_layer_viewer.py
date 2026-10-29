
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from src.cplugs.reviewboard import mcp, viewer
from src.cplugs.reviewboard.layers import inject, tool_schema
from src.cplugs.sdk import ToolError
from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR, make_board, make_root
from tests.python.cplugs.reviewboard.layer_fixtures import QUESTIONS, layer_sidecar

SLUG = SIDECAR["board"]["slug"]


def served(tmp_path: Path, raw: dict, view: str = "main") -> str:
    root = make_root(tmp_path)
    make_board(root, raw)
    return viewer.page(root, SLUG, "r1", view)[0].decode("utf-8")


def data_block(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="rb-layer">(.*?)</script>', html, re.S)
    assert match, "no data block"
    return json.loads(match.group(1))


def test_a_layer_revision_is_served_with_its_data_runtime_and_style(tmp_path: Path) -> None:
    html = served(tmp_path, layer_sidecar(QUESTIONS))
    assert data_block(html) == QUESTIONS | {"placement": "inline"}
    assert "<style data-rb-layer>" in html and "var RbLayerFields" in html and "rb-strings" in html
    assert html.index("window.rb = { send") < html.index('id="rb-layer"') < html.index("var RbLayerFields")


def test_the_runtime_is_one_function_with_the_fields_first() -> None:
    script = inject.runtime_script().decode("utf-8")
    assert script.startswith("<script>(function () {") and script.endswith("})();</script>")
    assert script.index("var RbLayerFields") < script.index("rb-strings") and "</script" not in script[:-9].lower()


@pytest.mark.parametrize("label", ["</script><script>alert(1)</script>", "a & b <!-- <script>", "line sep "])
def test_a_label_cannot_leave_the_data_block(tmp_path: Path, label: str) -> None:
    layer = copy.deepcopy(QUESTIONS)
    layer["items"][0]["label"] = label
    html = served(tmp_path, layer_sidecar(layer))
    block = re.search(r'id="rb-layer">(.*?)</script>', html, re.S).group(1)
    assert "<" not in block and ">" not in block and "&" not in block and " " not in block and " " not in block
    assert data_block(html)["items"][0]["label"] == label


def test_a_canvas_and_a_prompt_revision_are_served_byte_for_byte_as_before(tmp_path: Path) -> None:
    plain = served(tmp_path, copy.deepcopy(SIDECAR))
    assert plain.encode("utf-8") == viewer.inject(PAGE, viewer.bridge_script())
    canvas = copy.deepcopy(SIDECAR)
    canvas["revisions"][0].update(payload_mode=True, prompts=[])
    canvas["rounds"] = []
    (tmp_path / "canvas").mkdir()
    html = served(tmp_path / "canvas", canvas)
    assert "rb-layer" not in html and "data-rb-layer" not in html and "RbLayerFields" not in html


def test_an_extra_view_of_a_layer_revision_gets_no_layer(tmp_path: Path) -> None:
    raw = layer_sidecar(QUESTIONS)
    extra = dict(raw["revisions"][0]["views"][0], id="alt", label="alt", file="r001--alt.html")
    raw["revisions"][0]["views"].append(extra)
    root = make_root(tmp_path)
    make_board(root, raw).joinpath("r001--alt.html").write_bytes(PAGE)
    html = viewer.page(root, SLUG, "r1", "alt")[0].decode("utf-8")
    assert "rb-layer" not in html


def test_the_tool_offers_only_kinds_the_frame_draws() -> None:
    runtime = (inject.FRAME_DIR / "layer-fields.js").read_text(encoding="utf-8")
    makers = re.search(r"var MAKERS = \{(.*?)\};", runtime, re.S).group(1)
    drawn = set(re.findall(r"(\w+):", makers))
    for name in inject.RUNTIME_FILES:
        drawn |= set(re.findall(r"F\.register\('(\w+)'", (inject.FRAME_DIR / name).read_text(encoding="utf-8")))
    assert set(tool_schema.ITEM_KINDS) | {"row"} == drawn
    assert "rows" in tool_schema.LAYER_KINDS
    for name in ("task_manager_board_create", "task_manager_board_revision_add"):
        assert mcp.TOOLS[name].properties["layer"] is tool_schema.LAYER


@pytest.mark.parametrize("layer,ok", [({"kind": "questions"}, True), ({"kind": "rows"}, True), ({"kind": "canvas"}, False), (None, False)])
def test_a_questions_layer_may_leave_out_the_page(layer, ok: bool) -> None:
    args = {"summary": "s"} | ({"layer": layer} if layer else {})
    if ok:
        assert "html" not in mcp.file_pages(args)
    else:
        with pytest.raises(ToolError, match="exactly one of html"):
            mcp.file_pages(args)


def test_a_page_and_a_file_together_are_still_refused() -> None:
    with pytest.raises(ToolError, match="exactly one of html"):
        mcp.file_pages({"summary": "s", "html": "<p>", "file_path": "/x.html", "layer": {"kind": "questions"}})
