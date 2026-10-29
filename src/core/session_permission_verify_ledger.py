"""When each open permission claim's pane was last read.

The ladder in ``session_permission_verify`` is pure and the seam in
``session_permission_verify_apply`` does the tmux read; this holds the one
piece of mutable state between them, exactly the way
``session_startup_gate_ledger`` sits beside ``session_startup_gate``.

WHY THIS EXISTS AT ALL. The cost gate refuses every healthy session
outright - it is fail-closed, and unlike the startup gate's "no hook on
record" refusal a missing record here means "no claim", not "look now".
What it could not refuse was the RE-look: both verdicts that KEEP the flag
(the dialog is on screen, or the tail could not be read) leave the gate
passing again on the next poll, so a session whose claim is genuinely open
paid one ``capture-pane`` every 5s until a human answered it. That is a
subprocess on the synchronous listing path, which this codebase has
already paid for once in terminal latency.

IT IS KEYED ON THE CLAIM, NOT ON THE SESSION, and that is the whole
correctness argument. The key is ``(session_id, permission_opened_at)``,
and ``permission_opened_at`` is stamped by ``SessionActivityTracker`` only
when the flag goes False -> True. So a NEW ``PermissionRequest`` on the
same session carries a new stamp, finds no record, and is read
IMMEDIATELY - the throttle can never delay the first look at a claim,
which is the case the verification exists for. A session-keyed ledger
would have inherited the previous claim's reading and delayed it by up to
a full interval, silently, in the one situation that matters.

A CLAIM WITH NO STAMP IS NOT RECORDED. ``permission_open_since`` returns
None both when nothing is open and when the stamp was lost, and the gate
already refuses on that; a record keyed on None would be one bucket every
such session shared.

THE STORE HANGS OFF THE MANAGER through a ``WeakKeyDictionary``, the same
arrangement ``session_status_seed_read`` uses and for the same two
reasons: ``session_manager.py`` is far past the size guideline and under
concurrent edit, and a weak key means the store dies with its manager
rather than pinning one alive. A manager that cannot be weakly referenced
gets a throwaway store, which costs the throttle and never an error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple
from weakref import WeakKeyDictionary

ClaimKey = Tuple[str, datetime]

_STORES: "WeakKeyDictionary[Any, PermissionCheckLedger]" = WeakKeyDictionary()


class PermissionCheckLedger:

    def __init__(self) -> None:
        self._reads: Dict[ClaimKey, datetime] = {}

    @staticmethod
    def _key(
        session_id: Optional[str], opened_at: Optional[datetime]
    ) -> Optional[ClaimKey]:
        if not session_id or opened_at is None:
            return None
        return (session_id, opened_at)

    def last_check_at(
        self, session_id: Optional[str], opened_at: Optional[datetime]
    ) -> Optional[datetime]:
        key = self._key(session_id, opened_at)
        if key is None:
            return None
        return self._reads.get(key)

    def record_check(
        self,
        session_id: Optional[str],
        opened_at: Optional[datetime],
        *,
        now: datetime,
    ) -> None:
        key = self._key(session_id, opened_at)
        if key is None:
            return
        self._reads[key] = now

    def prune(self, live_session_ids: Iterable[str]) -> None:
        """Drop records for sessions the manager no longer holds.

        Description: the store is already bounded by the number of
            sessions with an OPEN claim, which is normally zero, but a
            long-lived process that churns sessions would otherwise keep
            a stale key per retired one. Records for a session that is
            still held are kept whatever their claim stamp says - a
            superseded claim's key is harmless and is never read again.
        Inputs: live_session_ids (iterable[str]).
        Output: None.
        Example: ledger.prune(registry.sessions.keys())
        """
        live = set(live_session_ids)
        for key in [k for k in self._reads if k[0] not in live]:
            self._reads.pop(key, None)


def ledger_for(manager: Any) -> PermissionCheckLedger:
    try:
        ledger = _STORES.get(manager)
        if ledger is None:
            ledger = PermissionCheckLedger()
            _STORES[manager] = ledger
        return ledger
    except TypeError:
        return PermissionCheckLedger()
