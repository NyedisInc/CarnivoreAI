
from __future__ import annotations

import hashlib
import json
from typing import Any, List, Mapping

import structlog

from src.cplugs.sdk.widget_decl import REQUIRED_FIXTURES

logger = structlog.get_logger()

GATE_SCHEMA = 1
MIN_THEMES = 2


class GateRefused(Exception):

    def __init__(self, widget: str, reasons: List[str]) -> None:
        super().__init__(f"{widget}: refused ({'; '.join(reasons)})")
        self.widget = widget
        self.reasons = reasons


def record_digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _missing(wanted: List[str], have: Any) -> List[str]:
    held = have if isinstance(have, list) else []
    return [name for name in wanted if name not in held]


def refusal_reasons(record: Mapping[str, Any], gate: Any) -> List[str]:
    if not isinstance(gate, Mapping):
        return ["no gate record: run scripts/widgets/gate.py"]
    reasons: List[str] = []
    if gate.get("schema") != GATE_SCHEMA:
        reasons.append(f"gate record schema is {gate.get('schema')!r}, this build reads {GATE_SCHEMA}")
    if gate.get("widget") != record.get("id"):
        reasons.append(f"gate record is for {gate.get('widget')!r}, not {record.get('id')!r}")
    if gate.get("record_sha256") != record_digest(record):
        reasons.append("the contract record changed after the gate ran: run it again")
    if gate.get("determined") is not True:
        reasons.append("the gate could not determine a verdict (the harness did not run)")
    if gate.get("ok") is not True:
        reasons.append("the gate did not pass")
    for key in ("failures",):
        if gate.get(key):
            reasons.append(f"{len(gate[key])} gate failure(s), first: {gate[key][0]}")
    for key in ("findings", "errors"):
        if gate.get(key):
            reasons.append(f"{gate[key]} {key} in the fixture scenarios")
    themes = gate.get("themes") if isinstance(gate.get("themes"), list) else []
    if len(themes) < MIN_THEMES:
        reasons.append(f"drawn under {len(themes)} theme(s), at least {MIN_THEMES} are required")
    for what, wanted in (("host", list(record.get("hosts", []))), ("size", list(record.get("sizes", []))),
                         ("fixture", list(REQUIRED_FIXTURES))):
        gone = _missing(wanted, gate.get(what + "s"))
        if gone:
            reasons.append(f"declared {what}(s) never drawn: {', '.join(gone)}")
    return reasons


def refuse_unless_passing(record: Mapping[str, Any], gate: Any) -> None:
    reasons = refusal_reasons(record, gate)
    if reasons:
        logger.warning("widget_gate_refused", widget=record.get("id"), reasons=reasons)
        raise GateRefused(str(record.get("id")), reasons)
