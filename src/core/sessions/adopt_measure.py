
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, Optional

from src.core.sessions.adopt_confirm import NOT_CONFIRMED

if TYPE_CHECKING:
    from src.core.claude_session_correlate_ladder import LadderResult
    from src.core.tmux_listing import TmuxListing


@dataclass(frozen=True)
class AdoptMeasurements:

    working_dir: Optional[str]
    pane_pid: Optional[int]
    pane_dead: Optional[bool]
    correlation: Optional["LadderResult"] = None
    takeover_refusal: Optional[str] = NOT_CONFIRMED

    def persist_probes(self) -> Dict[str, object]:
        return {
            "working_dir_probe": lambda _name: self.working_dir,
            "pane_pid_probe": lambda _name: self.pane_pid,
            "pane_dead_probe": lambda _name: self.pane_dead,
            "correlation": self.correlation,
            "takeover_refusal": self.takeover_refusal,
        }


def measure_adoption(socket: str, name: str, listing: Optional["TmuxListing"] = None) -> AdoptMeasurements:
    from src.core.session_adopt_dead_gate import make_pane_dead_probe
    from src.core.tmux_session_cwd import make_working_dir_probe
    from src.core.tmux_session_pane_pid import make_pane_pid_probe

    from src.core.sessions.adopt_takeover import confirm_for_takeover, measure_before_claim

    working_dir = make_working_dir_probe(socket)(name)
    pane_pid = make_pane_pid_probe(socket)(name)
    correlation = None if listing is None else measure_before_claim(
        listing, socket=socket, name=name, working_dir=working_dir, pane_pid=pane_pid
    )
    return AdoptMeasurements(
        working_dir=working_dir,
        pane_pid=pane_pid,
        pane_dead=make_pane_dead_probe(socket)(name),
        correlation=correlation,
        takeover_refusal=confirm_for_takeover(listing, name=name, correlation=correlation, working_dir=working_dir, pane_pid=pane_pid),
    )
