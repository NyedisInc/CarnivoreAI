
import asyncio
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Callable, Iterable, Optional

from src.core.session_startup_gate import should_capture_tail
from src.core.session_startup_gate_ledger import StartupGateLedger, capture_pane_tail
from src.core.session_status import LIVENESS_LIVE, resolve_listing_liveness
from src.core.session_status_map import StatusMap, listing_proves_alive
from src.core.hosts.identity import is_remote_backend


CaptureTail = Callable[..., Optional[str]]


@dataclass(frozen=True)
class GateInputs:

    pane_alive: Optional[bool]
    first_hook_at: Optional[datetime]
    age_seconds: Optional[float]


def gate_inputs(
    ledger: StartupGateLedger, tmux_name: str, row: Optional[dict], liveness: str
) -> GateInputs:
    epoch = row.get("created_at_epoch") if row else None
    ledger.observe_instance(tmux_name, epoch=epoch, pane_pid=row.get("pid") if row else None)
    age: Optional[float] = None
    if epoch is not None:
        try:
            age = max(0.0, time.time() - float(epoch))
        except (TypeError, ValueError):
            age = None
    return GateInputs(
        pane_alive=True if liveness == LIVENESS_LIVE else None,
        first_hook_at=ledger.first_hook_at(tmux_name),
        age_seconds=age,
    )


def wants_tail(ledger: StartupGateLedger, tmux_name: str, inputs: GateInputs) -> bool:
    return should_capture_tail(
        pane_alive=inputs.pane_alive,
        first_hook_at=inputs.first_hook_at,
        instance_age_seconds=inputs.age_seconds,
        tail_age_seconds=ledger.tail_age_seconds(tmux_name),
    )


def take_tail(
    ledger: StartupGateLedger, socket: str, tmux_name: str, capture: CaptureTail = capture_pane_tail
) -> Optional[str]:
    found, tail = ledger.pop_prefetched_tail(tmux_name)
    return tail if found else capture(socket=socket, name=tmux_name)


async def prefetch(
    manager, status_map: StatusMap, session_ids: Iterable[str], capture: CaptureTail = capture_pane_tail
) -> None:
    ledger: StartupGateLedger = manager._startup_gate_ledger
    wanted: list[tuple[str, str]] = []
    for sid in session_ids:
        sess = manager._registry.sessions.get(sid)
        backend = manager._registry.backends.get(sid)
        if sess is None or backend is None or is_remote_backend(backend):
            continue
        name = getattr(backend, "tmux_session", None)
        socket = getattr(backend, "socket_name", None)
        row = status_map.get(name) if name else None
        if not name or not socket or row is None:
            continue
        if not listing_proves_alive(status_map, name, backend_socket=socket):
            continue
        liveness = resolve_listing_liveness(exists=True, pane_status=row["status"])
        if wants_tail(ledger, name, gate_inputs(ledger, name, row, liveness)):
            wanted.append((socket, name))
    if not wanted:
        return
    tails = await asyncio.gather(
        *(asyncio.to_thread(capture, socket=sock, name=nm) for sock, nm in wanted)
    )
    for (_, nm), tail in zip(wanted, tails):
        ledger.stash_prefetched_tail(nm, tail)
