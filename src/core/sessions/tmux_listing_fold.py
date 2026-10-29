
from __future__ import annotations

from typing import Any, Callable, Dict, List, NamedTuple, Optional, Protocol, Sequence, Tuple, runtime_checkable

import structlog

from src.core.product_identity import TMUX_SESSION_PREFIX
from src.core.tmux_command_batch import COMMAND_SEPARATOR
from src.core.tmux_listing import REASON_EXIT_PREFIX, TmuxListing, coerce_listing
from src.core.tmux_listing_parse import (
    LISTING_FORMAT,
    is_plumbing_session,
    parse_listing_row,
    resolve_ownership,
    split_listing_rows,
)
from src.core.tmux_transport.pane_listing import PANE_LISTING_FORMAT, parse_pane_listing

logger = structlog.get_logger()

SESSION_ROW_TAG = "S|"
PANE_ROW_TAG = "P|"

FOLDED_LISTING_ARGS: Tuple[str, ...] = (
    "list-sessions", "-F", SESSION_ROW_TAG + LISTING_FORMAT,
    COMMAND_SEPARATOR,
    "list-panes", "-a", "-F", PANE_ROW_TAG + PANE_LISTING_FORMAT,
)

RunListing = Callable[..., Tuple[Optional[TmuxListing], str]]


class FoldedListing(NamedTuple):

    sessions: TmuxListing
    panes: Optional[TmuxListing]


def split_folded_rows(stdout_text: str) -> Tuple[List[str], List[str]]:
    rows = split_listing_rows(stdout_text)
    boundary = 0
    while boundary < len(rows) and rows[boundary].startswith(SESSION_ROW_TAG):
        boundary += 1
    sessions = [row[len(SESSION_ROW_TAG):] for row in rows[:boundary]]
    panes = [row[len(PANE_ROW_TAG):] if row.startswith(PANE_ROW_TAG) else row
             for row in rows[boundary:]]
    return sessions, panes


def reads_separately(failure: TmuxListing) -> bool:
    return not failure.ok and (failure.reason or "").startswith(REASON_EXIT_PREFIX)


def attachable_listing_from_rows(
    rows: Sequence[str],
    owned_names: Optional[set],
    owned_instances: Optional[set],
) -> TmuxListing:
    live_names: set = set()
    results: List[Dict[str, Any]] = []
    refused_rows = 0
    for line in rows:
        row = parse_listing_row(line)
        if row is None:
            refused_rows += 1
            if line.strip():
                logger.warning(
                    "list_attachable_sessions_unparseable_row",
                    raw=line.strip()[:200],
                    note="row did not match LISTING_FORMAT; refused rather than parsed on a best-effort basis",
                )
            continue
        name = row["name"]
        if is_plumbing_session(name):
            continue
        created_at_epoch = row["created_at_epoch"]
        live_names.add(name)
        created_by_cloude = resolve_ownership(
            name, created_at_epoch, owned_instances, owned_names, prefix=TMUX_SESSION_PREFIX)
        results.append({
            "name": name,
            "created_by_cloude": created_by_cloude,
            "created_at_epoch": created_at_epoch,
            "window_count": row["window_count"],
            "tmux_session_id": row["session_id"],
        })
    if owned_names:
        stale = owned_names - live_names
        if stale:
            logger.warning(
                "owned_tmux_sessions_not_in_live_listing",
                stale=sorted(stale),
                note="reconciler should prune these on next startup",
            )
    return TmuxListing.answered(results, refused_rows=refused_rows)


class FoldedRead:

    def __init__(self, run_listing: RunListing, owned_names: Optional[set],
                 owned_instances: Optional[set]) -> None:
        self._run_listing = run_listing
        self._owned_names = owned_names
        self._owned_instances = owned_instances
        self.sessions: Optional[TmuxListing] = None
        self.panes: Optional[TmuxListing] = None
        self.separate = False

    def load(self) -> TmuxListing:
        failure, stdout_text = self._run_listing(*FOLDED_LISTING_ARGS)
        if failure is not None:
            self.separate = reads_separately(failure)
            self.sessions = self.panes = failure
            return failure
        session_rows, pane_rows = split_folded_rows(stdout_text)
        self.sessions = attachable_listing_from_rows(session_rows, self._owned_names, self._owned_instances)
        rows, refused = parse_pane_listing("\n".join(pane_rows))
        self.panes = TmuxListing.answered(rows, refused_rows=refused)
        return self.panes


@runtime_checkable
class FoldingProbe(Protocol):

    def list_sessions_and_panes(self, owned_names: Optional[set] = None,
                                owned_instances: Optional[set] = None) -> FoldedListing:
        ...


class AttachableFold:

    def __init__(self) -> None:
        self._panes: Dict[str, TmuxListing] = {}

    def list_sessions(self, probe: Any, socket: str, owned_names: Optional[set],
                      owned_instances: Optional[set]) -> TmuxListing:
        if not isinstance(probe, FoldingProbe):
            return coerce_listing(probe.list_attachable_sessions(
                owned_names=owned_names, owned_instances=owned_instances))
        result = probe.list_sessions_and_panes(owned_names=owned_names, owned_instances=owned_instances)
        if result.panes is not None:
            self._panes[socket] = coerce_listing(result.panes)
        else:
            self._panes.pop(socket, None)
        return coerce_listing(result.sessions)

    def pane_listing(self, socket: str, build_probe: Callable[[], Any]) -> TmuxListing:
        kept = self._panes.get(socket)
        if kept is not None:
            return kept
        probe = build_probe()
        if not hasattr(probe, "list_pane_status_all"):
            return TmuxListing.answered([])
        return coerce_listing(probe.list_pane_status_all())
