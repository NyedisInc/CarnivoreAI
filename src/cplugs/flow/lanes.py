
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.cplugs.flow import edges
from src.cplugs.flow.transcript import LONG_TOOL_S, Scan

ScanFn = Callable[[Path, float, float, str], Scan]


def _tally(spans: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for span in spans:
        out[span["tool"]] = out.get(span["tool"], 0) + 1
    return out


def _long_blocks(out: Dict[str, Any], lane: str, scan: Scan, parent: str) -> None:
    for span in scan.spans:
        if span["end"] - span["start"] >= LONG_TOOL_S:
            out["blocks"].append({"id": f"{lane}:tool:{span['tool_use_id']}", "lane": lane, "kind": "tool", "start": span["start"],
                                  "end": span["end"], "label": span["tool"], "origin": None, "tools": {span["tool"]: 1},
                                  "parent": parent, "source": edges.source_ref(scan, span["line_from"], span["line_to"], span["uuid"])})


def _calls(out: Dict[str, Any], lane: str, scan: Scan) -> None:
    for span in scan.spans:
        out["calls"].append({"id": f"{lane}:call:{span['tool_use_id']}", "lane": lane, "tool": span["tool"], "start": span["start"],
                             "end": span["end"]})


def _says(out: Dict[str, Any], lane: str, scan: Scan, prompt_role: str = "prompt") -> None:
    for n, say in enumerate(scan.says):
        out["says"].append({"id": f"{lane}:say:{scan.conversation_id[-8:]}:{say['line']}:{n}", "lane": lane, "t": say["t"],
                            "role": prompt_role if say["role"] == "prompt" else say["role"], "text": say["text"],
                            "source": edges.source_ref(scan, say["line"], uuid=say["uuid"])})


def session_blocks(out: Dict[str, Any], lane: str, scans: List[Scan]) -> None:
    for scan in scans:
        for turn in scan.turns:
            block_id = f"{lane}:turn:{scan.conversation_id[:8]}:{turn['line_from']}"
            out["blocks"].append({"id": block_id, "lane": lane, "kind": "turn", "start": turn["start"], "end": max(turn["end"], turn["start"]),
                                  "label": turn["label"], "origin": turn["origin"], "tools": turn["tools"], "parent": None,
                                  "source": edges.source_ref(scan, turn["line_from"], turn["line_to"], turn.get("uuid"))})
        _long_blocks(out, lane, scan, "")
        _says(out, lane, scan)
        _calls(out, lane, scan)


def _read_meta(directory: Path, agent_id: str) -> Dict[str, Any]:
    try:
        data = json.loads((directory / f"agent-{agent_id}.meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def subagents(out: Dict[str, Any], parent_lane: str, scans: List[Scan], lo: float, hi: float, scan_fn: ScanFn) -> None:
    skipped = 0
    for scan in scans:
        if not scan.path:
            continue
        directory = Path(scan.path).with_suffix("") / "subagents"
        returns = {r["tool_use_id"]: r for r in scan.returns if r["tool_use_id"]}
        for launch in scan.launches:
            agent_id = launch["agent_id"]
            meta = _read_meta(directory, agent_id) if agent_id else {}
            if not agent_id or (meta.get("toolUseId") and meta["toolUseId"] != launch["tool_use_id"]):
                skipped += 1
                continue
            try:
                sub = scan_fn(directory / f"agent-{agent_id}.jsonl", lo, hi, f"{scan.conversation_id}/agent-{agent_id}")
            except OSError:
                sub = Scan(conversation_id=f"{scan.conversation_id}/agent-{agent_id}")
            sub.path = str(directory / f"agent-{agent_id}.jsonl")
            start = sub.first_t if sub.first_t is not None else launch["t"]
            end = sub.last_t if sub.last_t is not None else launch["t_result"]
            lane = f"a:{agent_id}"
            label = str(meta.get("description") or launch["description"] or "subagent")[:80]
            kind = meta.get("agentType") or launch["agent_type"]
            out["lanes"].append({"id": lane, "kind": "subagent", "label": f"{kind}: {label}" if kind else label, "session_uuid": None,
                                 "app_id": None, "parent": parent_lane, "agent_id": agent_id, "start": start})
            out["blocks"].append({"id": f"{lane}:run", "lane": lane, "kind": "subagent", "start": start, "end": max(end, start), "label": label,
                                  "origin": "subagent", "tools": _tally(sub.spans), "parent": None,
                                  "source": edges.source_ref(sub, 1, sub.records, None)})
            _long_blocks(out, lane, sub, f"{lane}:run")
            _says(out, lane, sub, prompt_role="task")
            _calls(out, lane, sub)
            out["edges"].append(edges.edge(f"launch:{launch['tool_use_id']}", "subagent_launch", parent_lane, launch["t"], lane, start, label,
                                           source={"send": edges.source_ref(scan, launch["line"], uuid=launch["uuid"])}))
            back = returns.get(launch["tool_use_id"])
            if back is not None:
                out["edges"].append(edges.edge(f"return:{launch['tool_use_id']}", "subagent_return", lane, max(end, start), parent_lane,
                                               max(back["t"], end), back["status"] or "returned",
                                               source={"receive": edges.source_ref(scan, back["line"], uuid=back["uuid"])}))
    if skipped:
        out["warnings"].append(f"{skipped} subagent launch(es) could not be matched to a transcript")
