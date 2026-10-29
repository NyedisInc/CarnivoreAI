
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from src.cplugs.reviewboard import document, schema
from src.cplugs.reviewboard.cli import emit_schema
from tests.python.cplugs.reviewboard.boards import SIDECAR, sidecar


def test_the_spec_example_round_trips_through_the_canonical_text() -> None:
    text = document.canonical_text(document.parse_sidecar(SIDECAR))
    assert json.loads(text) == SIDECAR
    assert text == json.dumps(SIDECAR, indent=2, ensure_ascii=False) + "\n"
    assert document.canonical_text(document.parse_sidecar(json.loads(text))) == text


def test_the_committed_json_schema_is_generated_from_the_models() -> None:
    assert emit_schema.SCHEMA_PATH.read_text(encoding="utf-8") == emit_schema.schema_text()
    out = io.StringIO()
    assert emit_schema.main(["--check"], out=out) == 0 and "current" in out.getvalue()


def test_unknown_keys_are_refused_outside_ext_and_kept_inside_it() -> None:
    typo = copy.deepcopy(SIDECAR)
    typo["revisions"][0]["sumary"] = "x"
    with pytest.raises(document.SidecarInvalid, match=r"revisions\[0\]\.sumary"):
        document.parse_sidecar(typo)
    kept = sidecar(ext={"themes": {"v": 2, "anything": {"deep": [1, "two"]}}})
    kept["rounds"][0]["ext"] = {"notes": {"v": 1, "points": [{"x": 3}]}}
    assert json.loads(document.canonical_text(document.parse_sidecar(kept))) == kept
    with pytest.raises(document.SidecarInvalid, match="ext"):
        document.parse_sidecar(sidecar(ext={"themes": {"anything": 1}}))


def test_a_newer_schema_version_is_classified_before_it_is_validated() -> None:
    newer = sidecar(schema_version=3, board={"made": "differently"})
    assert document.is_newer(newer) and not document.is_newer(SIDECAR)
    assert document.schema_version_of({"schema": "other", "schema_version": 3}) is None
    with pytest.raises(document.SidecarInvalid):
        document.parse_sidecar(newer)


def _mutate(path: str, value: Any) -> Callable[[Dict[str, Any]], None]:
    def apply(raw: Dict[str, Any]) -> None:
        node: Any = raw
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        last = parts[-1]
        node[int(last) if last.isdigit() else last] = value
    return apply


@pytest.mark.parametrize("mutate, message", [
    (_mutate("revisions.0.id", "r2"), "expected id r1"),
    (_mutate("revisions.0.views.0.file", "r002.html"), "must be r001.html"),
    (_mutate("revisions.0.views.0.id", "side"), "first view must be 'main'"),
    (_mutate("revisions.0.prompts.0.anchor", "nowhere"), "anchor nowhere is not declared"),
    (_mutate("revisions.0.prompts.1.options", [{"id": "a", "label": "x"}]), "has no options"),
    (_mutate("revisions.0.answers_round", "n1"), "not a round sent on an earlier revision"),
    (_mutate("rounds.0.revision", "r9"), "revision r9 does not exist"),
    (_mutate("rounds.0.answers.0.options", ["a", "b"]), "picks one of its options"),
    (_mutate("rounds.0.answers.0.options", ["z"]), "picks one of its options"),
    (_mutate("rounds.0.answers.1.text", "yes"), "carries checked and nothing else"),
    (_mutate("rounds.0.answers.2.text", "  "), "non-empty text"),
    (_mutate("rounds.0.anchor_notes", [{"anchor": "ghost", "text": "x"}]), "anchor ghost is not declared"),
    (_mutate("rounds.0.unanswered", ["layout"]), "layout is not an unanswered prompt"),
    (_mutate("rounds.0.note", "x" * 8000), "the limit for one round is 8000"),
    (_mutate("rounds.0.delivery", {"state": "undelivered"}), "says why"),
    (_mutate("rounds.0.context.view", "side"), "side is not a view of r1"),
    (_mutate("board.created_at", "2026-13-40T00:00:00Z"), "created_at"),
    (_mutate("board.slug", "bottom-bar"), "board.slug"),
    (_mutate("task.github_issue", "CarnivoreAIDev 1700"), "github_issue"),
])
def test_the_rules_refuse_a_broken_sidecar(mutate: Callable[[Dict[str, Any]], None], message: str) -> None:
    raw = copy.deepcopy(SIDECAR)
    document.parse_sidecar(raw)
    mutate(raw)
    with pytest.raises(document.SidecarInvalid, match=message):
        document.parse_sidecar(raw)


def test_a_second_send_of_one_draft_is_refused_as_a_second_round() -> None:
    raw = copy.deepcopy(SIDECAR)
    twin = copy.deepcopy(raw["rounds"][0])
    twin.update(id="n2", n=2)
    raw["rounds"].append(twin)
    with pytest.raises(document.SidecarInvalid, match="client_round_id"):
        document.parse_sidecar(raw)


def _committed(slug: str) -> Dict[str, Any]:
    path = Path(__file__).resolve().parents[4] / "design" / "boards" / slug / document.SIDECAR_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def _views(raw: Dict[str, Any], index: int, name: str) -> None:
    for view in raw["revisions"][index]["views"]:
        view["file"] = name if view["id"] == "main" else name.replace(".html", f"--{view['id']}.html")


@pytest.mark.parametrize("slug, change", [
    ("20261012-target-flow", lambda raw: raw["revisions"][0].pop("ext")),
    ("20261012-target-flow", lambda raw: _views(raw, 1, "r001.html")),
    ("20261012-current-flow", lambda raw: _views(raw, 1, "r001.html")),
    ("20261012-current-flow", lambda raw: raw["revisions"][0]["ext"]["legacy"].update(reconstructed=False)),
])
def test_only_a_reconstructed_revision_shares_a_later_revisions_file(slug: str, change: Callable[[Dict[str, Any]], None]) -> None:
    raw = _committed(slug)
    document.parse_sidecar(raw)
    change(raw)
    with pytest.raises(document.SidecarInvalid, match="own file for view"):
        document.parse_sidecar(raw)


def test_a_view_file_name_past_four_digits_is_refused_by_shape() -> None:
    raw = copy.deepcopy(SIDECAR)
    raw["revisions"][0]["views"][0]["file"] = "r" + "1" * 5000 + ".html"
    with pytest.raises(document.SidecarInvalid, match=r"views\[0\]\.file"):
        document.parse_sidecar(raw)


def test_the_revision_and_round_counts_are_capped() -> None:
    raw = copy.deepcopy(SIDECAR)
    raw["revisions"] = raw["revisions"] * (schema.MAX_REVISIONS + 1)
    with pytest.raises(document.SidecarInvalid, match="revisions"):
        document.parse_sidecar(raw)
    raw = copy.deepcopy(SIDECAR)
    raw["rounds"] = raw["rounds"] * (schema.MAX_ROUNDS + 1)
    with pytest.raises(document.SidecarInvalid, match="rounds"):
        document.parse_sidecar(raw)


def test_an_extension_block_nested_past_the_limit_is_refused() -> None:
    deep: Any = []
    for _ in range(schema.MAX_EXT_DEPTH - 2):
        deep = [deep]
    document.canonical_text(document.parse_sidecar(sidecar(ext={"themes": {"v": 1, "x": deep}})))
    with pytest.raises(document.SidecarInvalid, match="nest at most"):
        document.parse_sidecar(sidecar(ext={"themes": {"v": 1, "x": [deep]}}))
