
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.core import product_identity
from src.core.tmux_listing_parse import is_plumbing_session

Runner = Callable[[List[str]], Optional[str]]

READ_ONLY_SUBCOMMANDS = frozenset({"display-message", "list-sessions", "list-panes"})


def sockets_to_report(configured: Optional[str]) -> Tuple[str, ...]:
    ordered = [configured] if configured else []
    ordered.extend(product_identity.sockets_to_probe(None))
    return tuple(dict.fromkeys(ordered))


def tmux_argv(tmux: str, socket: str, *command: str) -> List[str]:
    if not command or command[0] not in READ_ONLY_SUBCOMMANDS:
        raise ValueError(f"tmux subcommand not allowed in diagnostics: {command[:1]}")
    return [tmux, "-L", socket, *command]


def _lines(out: Optional[str]) -> Optional[List[str]]:
    return None if out is None else [line for line in out.splitlines() if line.strip()]


def collect_socket(run: Runner, tmux: str, socket: str) -> Dict[str, Any]:
    names = _lines(run(tmux_argv(tmux, socket, "list-sessions", "-F", "#{session_name}")))
    names = [n for n in names if not is_plumbing_session(n)] if names is not None else None
    pid_text = run(tmux_argv(tmux, socket, "display-message", "-p", "#{pid}")) if names is not None else None
    pid = int(pid_text.strip()) if pid_text and pid_text.strip().isdigit() else None
    owned = sorted(n for n in (names or []) if product_identity.is_owned_session_name(n))
    dead: List[str] = []
    if owned:
        panes = _lines(run(tmux_argv(tmux, socket, "list-panes", "-a", "-F", "#{session_name} #{pane_dead}"))) or []
        for row in panes:
            name, _, flag = row.rpartition(" ")
            if flag == "1" and name in owned and name not in dead:
                dead.append(name)
    return {
        "socket": socket,
        "server_pid": pid,
        "sessions": owned if names is not None else None,
        "other_session_count": len(names) - len(owned) if names is not None else None,
        "dead_pane_sessions": sorted(dead),
    }


def collect(run: Runner, tmux: Union[str, Callable[[str], str]], configured: Optional[str]) -> List[Dict[str, Any]]:
    return [collect_socket(run, tmux(socket) if callable(tmux) else tmux, socket) for socket in sockets_to_report(configured)]
