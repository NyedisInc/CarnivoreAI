
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.attention_history.store import DB_NAME, read_spans
from src.core.session_timeline.assemble import parse_time


def attach(answer: Dict[str, Any], state_dir: Path) -> Dict[str, Any]:
    starts = [t for b in answer.get("bars") or [] if (t := parse_time(b.get("started_at"))) is not None]
    now = parse_time(answer.get("now"))
    floor: Optional[Any] = min(starts) if starts else None
    out: List[Dict[str, Any]] = []
    for span in read_spans(state_dir / DB_NAME, answer["session_uuid"]):
        start, end = parse_time(span["start"]), parse_time(span["end"])
        if start is None or (end is not None and floor is not None and end <= floor) or (now and start > now):
            continue
        if floor is not None and start < floor:
            start = floor
        out.append({"kind": span["kind"], "start": start.isoformat(), "end": end.isoformat() if end else None})
    answer["attention"] = out
    return answer
