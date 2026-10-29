
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class AdoptMeasurements:

    working_dir: Optional[str]
    pane_pid: Optional[int]
    pane_dead: Optional[bool]

    def persist_probes(self) -> Dict[str, Callable[..., object]]:
        return {
            "working_dir_probe": lambda _name: self.working_dir,
            "pane_pid_probe": lambda _name: self.pane_pid,
            "pane_dead_probe": lambda _name: self.pane_dead,
        }


def measure_adoption(socket: str, name: str) -> AdoptMeasurements:
    from src.core.session_adopt_dead_gate import make_pane_dead_probe
    from src.core.tmux_session_cwd import make_working_dir_probe
    from src.core.tmux_session_pane_pid import make_pane_pid_probe

    return AdoptMeasurements(
        working_dir=make_working_dir_probe(socket)(name),
        pane_pid=make_pane_pid_probe(socket)(name),
        pane_dead=make_pane_dead_probe(socket)(name),
    )
