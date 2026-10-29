
from __future__ import annotations

import json
from typing import Dict, Tuple

import pytest

from src.core.message_model_serialize import (
    APPEARANCE_KEYS,
    KEY_ORDER_NOT_AN_OBJECT,
    STYLE_NAMES,
    reassemble,
    render_line,
)
from tests.jsonl_shape_fixture_data import (
    ENVELOPE_KEYS,
    FIXTURES,
    NOT_AN_OBJECT,
    ShapeFixture,
    split_line,
)
from tests.jsonl_shape_support import load_manifest

REASSEMBLY_DIMENSIONS: Tuple[str, ...] = (
    "line_status", "serializer_style", "render_source", "body_row",
    "envelope_keys", "line_ending", "has_trailing_newline",
    "body_toplevel_type",
)

EXPECTED_REASSEMBLY_CLASSES: int = 6


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_reassembly_reproduces_the_hand_authored_line(fixture: ShapeFixture):
    body, envelope = split_line(fixture.line, fixture.key_order)
    key_order = (
        KEY_ORDER_NOT_AN_OBJECT if fixture.key_order == NOT_AN_OBJECT
        else fixture.key_order
    )
    produced = render_line(body, envelope, key_order, fixture.style)
    assert produced == fixture.line, (
        f"reassembly no longer reproduces {fixture.name}\n"
        f"  covers:   {fixture.covers}\n"
        f"  expected: {fixture.line!r}\n"
        f"  produced: {produced!r}"
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_envelope_split_matches_what_the_fixture_declares(
    fixture: ShapeFixture,
):
    _, envelope = split_line(fixture.line, fixture.key_order)
    assert sorted(envelope) == sorted(fixture.envelope_keys_expected), (
        f"{fixture.name} declares envelope keys "
        f"{sorted(fixture.envelope_keys_expected)} but carries "
        f"{sorted(envelope)}"
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_reassemble_restores_key_order_position_for_position(
    fixture: ShapeFixture,
):
    if fixture.key_order == NOT_AN_OBJECT:
        pytest.skip("a non-object line has no key order to restore")
    body, envelope = split_line(fixture.line, fixture.key_order)
    rebuilt = reassemble(body, envelope, fixture.key_order)
    assert list(rebuilt.keys()) == list(fixture.key_order)


def test_appearance_key_set_has_not_changed():
    assert tuple(ENVELOPE_KEYS) == tuple(APPEARANCE_KEYS), (
        "APPEARANCE_KEYS changed. Every fixture's envelope split is now "
        "describing a different partition; review them, then update "
        "ENVELOPE_KEYS in tests/jsonl_shape_fixture_data.py"
    )
    assert NOT_AN_OBJECT == KEY_ORDER_NOT_AN_OBJECT


def test_every_registered_serializer_style_has_a_fixture():
    covered = {fixture.style for fixture in FIXTURES}
    missing = sorted(set(STYLE_NAMES) - covered)
    assert not missing, f"no fixture exercises these styles: {missing}"


def _reassembly_class(dimensions: Dict[str, object]) -> str:
    return json.dumps(
        {name: dimensions[name] for name in REASSEMBLY_DIMENSIONS},
        sort_keys=True, separators=(",", ":"),
    )


def test_the_six_reassembly_classes_cover_every_signature():
    manifest = load_manifest()
    classes: Dict[str, int] = {}
    for entry in manifest["signatures"]:
        key = _reassembly_class(entry["dimensions"])
        classes[key] = classes.get(key, 0) + 1
    assert len(classes) == EXPECTED_REASSEMBLY_CLASSES, (
        f"the corpus now holds {len(classes)} distinct reassembly classes, "
        f"not {EXPECTED_REASSEMBLY_CLASSES}. Every class needs a hand-"
        "authored fixture before this number is raised:\n"
        + "\n".join(f"  {count:5d} signatures  {key}"
                    for key, count in sorted(classes.items(),
                                             key=lambda kv: -kv[1]))
    )
    assert sum(classes.values()) == len(manifest["signatures"])


def test_fixture_names_and_lines_are_unique():
    names = [fixture.name for fixture in FIXTURES]
    assert len(set(names)) == len(names), "duplicate fixture name"
    lines = [fixture.line for fixture in FIXTURES]
    assert len(set(lines)) == len(lines), "two fixtures carry the same line"


def test_fixture_lines_are_single_lines():
    for fixture in FIXTURES:
        assert "\n" not in fixture.line, (
            f"{fixture.name} contains a raw newline; escape it as \\n "
            "inside the JSON string instead"
        )
