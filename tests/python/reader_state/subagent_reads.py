
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.subagents import parent_index, parked_launches
from tests.python.reader_state import fixture_subagents as fx

LEDGER, PROMPT = "subagents.launch_ledger", "subagents.prompt_mark"
INDEX, SPAWNER, NOTICES = "subagents.completion_index", "subagents.spawner_index", "subagents.agent_notices"
NAMES = (LEDGER, PROMPT, INDEX, SPAWNER, NOTICES)


def _index_out(index: Optional[parent_index.CompletionIndex]) -> Any:
    if index is None:
        return None
    return {side: {k: (e.at.isoformat(), e.status) for k, e in ends.items()}
            for side, ends in (("a", index.by_agent_id), ("t", index.by_tool_use))}


def _install_spies(starts: Dict[str, List[str]]) -> None:
    real_launch, real_prompt, real_lines = (
        parked_launches._scan_launches, parked_launches._scan_prompts, parent_index.scan_parent_lines)

    def note(name: str, handle: Any) -> None:
        if handle.tell() == 0:
            starts[name].append(Path(handle.name).stem)

    def launches(handle: Any, ledger: Any, agent: str) -> Any:
        note(LEDGER, handle)
        return real_launch(handle, ledger, agent)

    def prompts(handle: Any, mark: Any, unused: str) -> Any:
        note(PROMPT, handle)
        return real_prompt(handle, mark, unused)

    def lines(handle: Any, index: Any, *, spawner: bool = False) -> Any:
        stem = Path(handle.name).stem
        note(SPAWNER if spawner else NOTICES if stem.startswith("agent-") else INDEX, handle)
        return real_lines(handle, index, spawner=spawner)

    parked_launches._scan_launches, parked_launches._scan_prompts = launches, prompts
    parent_index.scan_parent_lines = lines


def read_all(root: Path) -> Dict[str, Dict[str, Any]]:
    starts: Dict[str, List[str]] = {name: [] for name in NAMES}
    _install_spies(starts)
    p0, p1 = fx.parent_path(root, "p0"), fx.parent_path(root, "p1")
    out: Dict[str, Any] = {name: {} for name in NAMES}
    out[LEDGER] = {p.stem: [[_launch(launch), retired] for launch, retired in
                            (parked_launches.conversation_launches(p) or [])] for p in (p0, p1)}
    out[PROMPT] = {p.stem: _iso(parked_launches.newest_real_prompt(p)) for p in (p0, p1)}
    out[INDEX] = {p.stem: _index_out(parent_index.read_completion_index(p)) for p in (p0, p1)}
    spawner = fx.agent_path(root, fx.SPAWNER)
    out[SPAWNER] = {spawner.stem: _index_out(parent_index.read_completion_index(spawner, spawner=True))}
    out[NOTICES] = {fx.agent_path(root, i).stem: _index_out(parent_index.read_completion_index(
        fx.agent_path(root, i), cache=parked_launches._AGENT_NOTICES)) for i in range(fx.N_AGENTS)}
    return {name: {"md5": hashlib.md5(json.dumps(out[name], sort_keys=True).encode()).hexdigest(),
                   "cold_parses": sorted(starts[name]), "nonempty": _count(out[name])}
            for name in NAMES}


def _iso(value: Any) -> Optional[str]:
    return None if value is None else value.isoformat()


def _launch(launch: Any) -> Dict[str, Any]:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in vars(launch).items()}


def _count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count(v) for v in value.values())
    if isinstance(value, list):
        return len(value) if value else 0
    return 0 if value is None else 1
