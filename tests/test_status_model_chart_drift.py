
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest

from src.core.db_models import (
    SESSION_LIFECYCLES,
    SESSION_ORIGINS,
)
from src.core.session_lifecycle import (
    RECONCILE_EVALUATED,
    RECONCILE_LISTING_INCOMPLETE,
    RECONCILE_NO_TABLE,
    RECONCILE_PROBE_UNAVAILABLE,
)
from src.core.session_respawn import ALL_RESPAWN_KINDS
from src.core.session_status import ALL_ACTIVITY_STATUSES, ALL_STATUSES

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "session-status-model.md"
TRAY_PATH = REPO_ROOT / "macOS" / "tray-status.js"
STATUS_UI_PATH = REPO_ROOT / "client" / "js" / "session-status-ui.js"

AXIS_ACTIVITY = "activity"
AXIS_LIFECYCLE = "lifecycle"
AXIS_ORIGIN = "origin"
AXIS_RECONCILE = "reconcile"
AXIS_RESPAWN = "respawn"
AXIS_TRAY = "tray"


def _doc_text() -> str:
    assert DOC_PATH.is_file(), f"chart document missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def _tray_states() -> Tuple[str, ...]:
    text = TRAY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+TRAY_STATES\s*=\s*Object\.freeze\(\[(.*?)\]\)",
        text,
        re.DOTALL,
    )
    assert match, "could not locate TRAY_STATES in macOS/tray-status.js"
    states = tuple(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert states, "TRAY_STATES parsed as empty - the parser is broken"
    return states


def _status_ui_label_keys() -> Set[str]:
    text = STATUS_UI_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+STATUS_LABELS\s*=\s*\{(.*?)\n    \};",
        text,
        re.DOTALL,
    )
    assert match, "could not locate STATUS_LABELS in session-status-ui.js"
    keys = set(re.findall(r"^\s{8}([a-z_]+):", match.group(1), re.MULTILINE))
    assert keys, "STATUS_LABELS parsed as empty - the parser is broken"
    return keys


def _inventory() -> Set[Tuple[str, str]]:
    match = re.search(
        r"```state-inventory\n(.*?)```", _doc_text(), re.DOTALL
    )
    assert match, "docs/session-status-model.md has no state-inventory block"
    pairs: Set[Tuple[str, str]] = set()
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        assert len(parts) == 3, f"malformed inventory line: {line!r}"
        name, axis, symbol = parts
        assert symbol, f"inventory line has no defining symbol: {line!r}"
        pairs.add((name, axis))
    assert pairs, "state-inventory block parsed as empty"
    return pairs


def _mermaid_text() -> str:
    blocks = re.findall(r"```mermaid\n(.*?)```", _doc_text(), re.DOTALL)
    assert blocks, "the chart document contains no mermaid blocks"
    return "\n".join(blocks)


def _code_vocabulary() -> Dict[str, Set[str]]:
    return {
        AXIS_ACTIVITY: set(ALL_STATUSES) | set(ALL_ACTIVITY_STATUSES),
        AXIS_LIFECYCLE: set(SESSION_LIFECYCLES),
        AXIS_ORIGIN: set(SESSION_ORIGINS),
        AXIS_RECONCILE: {
            RECONCILE_EVALUATED,
            RECONCILE_PROBE_UNAVAILABLE,
            RECONCILE_LISTING_INCOMPLETE,
            RECONCILE_NO_TABLE,
        },
        AXIS_RESPAWN: set(ALL_RESPAWN_KINDS),
        AXIS_TRAY: set(_tray_states()),
    }


@pytest.mark.parametrize("axis", sorted(_code_vocabulary()))
def test_every_code_state_is_in_the_inventory(axis: str) -> None:
    documented = {name for name, ax in _inventory() if ax == axis}
    defined = _code_vocabulary()[axis]
    missing = defined - documented
    assert not missing, (
        f"axis {axis!r}: these states exist in the code and are NOT in "
        f"docs/session-status-model.md's state-inventory block: "
        f"{sorted(missing)}"
    )


@pytest.mark.parametrize("axis", sorted(_code_vocabulary()))
def test_every_inventory_state_exists_in_code(axis: str) -> None:
    documented = {name for name, ax in _inventory() if ax == axis}
    defined = _code_vocabulary()[axis]
    invented = documented - defined
    assert not invented, (
        f"axis {axis!r}: the chart document names these states, and no "
        f"constant in the code defines them: {sorted(invented)}"
    )


def test_inventory_axes_are_exactly_the_known_axes() -> None:
    axes = {axis for _name, axis in _inventory()}
    assert axes == set(_code_vocabulary()), (
        f"inventory axes {sorted(axes)} do not match the axes this test "
        f"verifies {sorted(_code_vocabulary())}"
    )


def _drawn_states() -> Set[str]:
    charts = _mermaid_text()
    drawn: Set[str] = set()
    drawn |= set(
        re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[|\(\()", charts)
    )
    drawn |= set(
        re.findall(r"-->\s*(?:\|[^|]*\|\s*)?([A-Za-z_][A-Za-z0-9_]*)", charts)
    )
    drawn |= set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*-->", charts))
    for label in re.findall(r'\["(.*?)"\]', charts):
        drawn.add(label.split("<br/>")[0].split(" - ")[0].strip())
    assert drawn, "no mermaid nodes parsed - the chart parser is broken"
    return drawn


def test_every_inventory_state_is_drawn_in_a_chart() -> None:
    drawn = _drawn_states()
    undrawn = sorted({name for name, _axis in _inventory() if name not in drawn})
    assert not undrawn, (
        "these states are listed in the inventory but are drawn as a node "
        f"in no mermaid chart in the document: {undrawn}"
    )


def test_client_status_vocabulary_is_the_documented_mixture() -> None:
    expected = set(ALL_ACTIVITY_STATUSES) | {"stopped", "running", "asleep"}
    assert _status_ui_label_keys() == expected, (
        "client/js/session-status-ui.js STATUS_LABELS changed. Update "
        "docs/session-status-model.md (inventory AND the disagreements "
        "section) in the same change."
    )


def test_running_is_in_all_statuses_and_not_in_activity_statuses() -> None:
    assert "running" in ALL_STATUSES
    assert "running" not in ALL_ACTIVITY_STATUSES
    assert "ALL_ACTIVITY_STATUSES" in _doc_text()


def test_no_lifecycle_named_dead() -> None:
    assert "dead" not in SESSION_LIFECYCLES
    assert "dead" in ALL_STATUSES
