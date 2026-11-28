
from __future__ import annotations

import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.deepsearch import fallback_hook
from src.plugins.save.offload import constants as C, push
from src.plugins.save.offload import homes as offload_homes
from src.plugins.save.offload import move
from src.plugins.save.offload.eligibility import ConversationVerdict, Evaluator
from src.plugins.save.offload.ledger import OPERATION, Entry, Ledger, LedgerUnreadable
from src.plugins.save.offload.report import Readiness
from src.plugins.save.offload.verify import VerifyFailed, Verified, verify_conversation
from src.plugins.save.vault.store import Vault, unit_lock
from src.plugins.save.vault.units import Scanner, UnitPlan
from src.plugins.sdk.session_chains import RunningScan

logger = structlog.get_logger()

STATUS_OFFLOADED = "offloaded"
STATUS_WOULD_OFFLOAD = "would_offload"


class OffloadRefused(RuntimeError):

    def __init__(self, code: str, detail: str, reasons: Tuple[str, ...] = (), stuck: Tuple[str, ...] = ()) -> None:
        super().__init__(detail)
        self.code, self.detail, self.reasons, self.stuck = code, detail, reasons, stuck


class UnknownSession(LookupError):
    pass


@dataclass
class ConversationOutcome:

    conversation_id: str
    status: str
    point_id: Optional[str]
    files: int
    bytes: int
    holding_dir: str = ""


@dataclass
class OffloadResult:

    session_uuid: str
    dry_run: bool
    conversations: List[ConversationOutcome] = field(default_factory=list)
    already_offloaded: List[str] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(c.bytes for c in self.conversations)


def _check_eligible(evaluator: Evaluator, ready: Readiness, session_uuid: str) -> Tuple[List[ConversationVerdict], List[ConversationVerdict]]:
    if not ready.ready:
        raise OffloadRefused(C.CODE_NOT_READY, "the install is not ready to offload: " + ", ".join(ready.blockers), ready.blockers)
    verdict = evaluator.session(session_uuid)
    if verdict is None:
        raise UnknownSession(session_uuid)
    if not verdict.offloadable:
        code = C.CODE_NOT_READY if C.REASON_NOT_READY in verdict.reasons else C.CODE_NOT_ELIGIBLE
        raise OffloadRefused(code, "this session cannot be offloaded now: " + ", ".join(verdict.reasons), verdict.reasons)
    return [v for v in verdict.conversations if v.on_disk], [v for v in verdict.conversations if not v.on_disk]


def _verify_all(vault: Vault, scanner: Scanner, conversations: List[str], homes: Dict[str, Path]) -> Dict[str, Tuple[UnitPlan, Verified]]:
    out: Dict[str, Tuple[UnitPlan, Verified]] = {}
    for conv in conversations:
        plan = scanner.plan_claude(conv)
        point = vault.manifests.newest(conv)
        if plan is None or point is None:
            raise OffloadRefused(C.CODE_VERIFY_FAILED, f"{conv}: no files on disk or no vault point to check them against")
        elsewhere = offload_homes.misplaced(plan.files, homes)
        if elsewhere:
            raise OffloadRefused(C.CODE_VERIFY_FAILED, f"{conv}: {elsewhere}")
        try:
            out[conv] = (plan, verify_conversation(vault.blobs, plan, point))
        except VerifyFailed as exc:
            raise OffloadRefused(C.CODE_VERIFY_FAILED, f"{conv}: {exc.detail}") from exc
    return out


def _entry(conv: ConversationVerdict, plan: UnitPlan, proof: Verified, holding_root: Path, now: float) -> Entry:
    return Entry(conversation_id=conv.conversation_id, unit=plan.unit, family=plan.family, encoded_folder=plan.encoded_folder, point_id=proof.point_id,
                 manifest_sha256=proof.manifest_sha256, files=proof.files, bytes=proof.bytes, group=list(conv.owners), state=C.STATE_OFFLOADING,
                 offloaded_at=now, holding_dir=str(Path(holding_root) / plan.unit), purge_after=now + C.HOLD_SECONDS)


def _ledger_try(action: Callable[[], object], what: str) -> None:
    try:
        action()
    except (LedgerUnreadable, OSError) as exc:
        logger.error("offload_ledger_undo_failed", what=what, error_type=type(exc).__name__, error=str(exc)[:200])


def _join_group(ledger: Ledger, conversation_id: str, owners: Tuple[str, ...]) -> None:
    held = ledger.get(conversation_id)
    if held is not None:
        ledger.update(conversation_id, group=sorted(set(held.group) | set(owners)))


def _roll_back(ledger: Ledger, done: List[Tuple[str, Tuple[move.Moved, ...]]], pending: List[str]) -> Tuple[str, ...]:
    stuck: List[str] = []
    for conv, moved in reversed(done):
        left = move.move_back(moved)
        stuck += left
        if left:
            _ledger_try(lambda c=conv, n=len(left), f=left[0]: ledger.update(c, state=C.STATE_FAILED, error=f"{n} file(s) could not be put back: {f}"), conv)
        else:
            _ledger_try(lambda c=conv: ledger.remove(c), conv)
    for conv in pending:
        _ledger_try(lambda c=conv: ledger.remove(c), conv)
    return tuple(stuck)


def _in_use(running_now: Callable[[], RunningScan], order: List[str]) -> bool:
    running = running_now()
    return running.unreadable or any(c in running.conversations for c in order)


def _refuse_in_use(stuck: Tuple[str, ...] = ()) -> OffloadRefused:
    return OffloadRefused(C.CODE_IN_USE, "a Claude process has one of these conversations open, or the process list could not be read", (C.REASON_IN_USE,), stuck)


def _move_all(ledger: Ledger, order: List[str], holding_root: Path, plans: Dict[str, Tuple[UnitPlan, Verified]], running_now: Callable[[], RunningScan]) -> None:
    done: List[Tuple[str, Tuple[move.Moved, ...]]] = []
    for index, conv in enumerate(order):
        try:
            moved = move.move_to_holding(plans[conv][0].files, holding_root, conv, plans[conv][1].stats)
            done.append((conv, moved))
            ledger.update(conv, state=C.STATE_OFFLOADED)
        except move.MoveRefused as exc:
            if exc.stuck:
                _ledger_try(lambda c=conv, n=len(exc.stuck), f=exc.stuck[0]: ledger.update(c, state=C.STATE_FAILED, error=f"{n} file(s) could not be put back: {f}"), conv)
            stuck = _roll_back(ledger, done, order[index + 1:] if exc.stuck else order[index:])
            raise OffloadRefused(exc.code, exc.detail, (), tuple(stuck) + tuple(exc.stuck)) from exc
        except (LedgerUnreadable, OSError) as exc:
            stuck = _roll_back(ledger, done, order[index:])
            raise OffloadRefused(C.CODE_LEDGER_UNREADABLE, f"the offload ledger could not be updated: {exc}", (), stuck) from exc
    if _in_use(running_now, order):
        raise _refuse_in_use(_roll_back(ledger, done, []))


def tell_index(conversations: Iterable[str]) -> None:
    for conv in conversations:
        fallback_hook.notify_conversation_gone(conv)


@push.coalescing
def offload_session(session_uuid: str, *, evaluator: Evaluator, ready: Readiness, vault: Vault, scanner: Scanner, ledger: Ledger, holding_root: Path,
                    running_now: Callable[[], RunningScan], homes: Dict[str, Path], dry_run: bool = False, now: Optional[float] = None) -> OffloadResult:
    clock = time.time() if now is None else now
    on_disk, away = _check_eligible(evaluator, ready, session_uuid)
    try:
        already = [v.conversation_id for v in away if ledger.get(v.conversation_id) is not None]
    except LedgerUnreadable as exc:
        raise OffloadRefused(C.CODE_LEDGER_UNREADABLE, f"the offload ledger cannot be read: {exc}") from exc
    result = OffloadResult(session_uuid, dry_run, already_offloaded=already)
    if not on_disk:
        raise OffloadRefused(C.CODE_NOT_ELIGIBLE, "nothing of this session is on disk to offload", (C.REASON_NOTHING_ON_DISK,))
    if dry_run:
        result.conversations = [ConversationOutcome(v.conversation_id, STATUS_WOULD_OFFLOAD, v.point_id, v.files, v.bytes) for v in on_disk]
        return result
    if not OPERATION.acquire(blocking=False):
        raise OffloadRefused(C.CODE_BUSY, "another offload or restore is running; try again when it has finished")
    try:
        order = sorted(v.conversation_id for v in on_disk)
        with ExitStack() as stack:
            for conv in order:
                stack.enter_context(unit_lock(conv))
            if _in_use(running_now, order):
                raise _refuse_in_use()
            plans = _verify_all(vault, scanner, order, homes)
            verdicts = {v.conversation_id: v for v in on_disk}
            try:
                for conv in order:
                    ledger.put(_entry(verdicts[conv], plans[conv][0], plans[conv][1], holding_root, clock))
            except (LedgerUnreadable, OSError) as exc:
                _roll_back(ledger, [], order)
                raise OffloadRefused(C.CODE_LEDGER_UNREADABLE, f"the offload ledger could not be written: {exc}") from exc
            if _in_use(running_now, order):
                _roll_back(ledger, [], order)
                raise _refuse_in_use()
            _move_all(ledger, order, holding_root, plans, running_now)
        for v in away:
            _ledger_try(lambda c=v.conversation_id, o=v.owners: _join_group(ledger, c, o), v.conversation_id)
    finally:
        OPERATION.release()
    tell_index(order)
    result.conversations = [ConversationOutcome(c, STATUS_OFFLOADED, plans[c][1].point_id, plans[c][1].files, plans[c][1].bytes, str(Path(holding_root) / c)) for c in order]
    logger.info("offload_done", session_uuid=session_uuid, conversations=len(order), bytes=result.bytes)
    return result
