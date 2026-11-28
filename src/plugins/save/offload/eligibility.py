
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.save.offload.chain import ChainMap, build
from src.plugins.save.vault.manifest import FileEntry, Manifest, ManifestError
from src.plugins.save.vault.store import Vault
from src.plugins.save.vault.units import Scanner, UnitPlan
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from src.plugins.sdk.transcript_files import dataless

logger = structlog.get_logger()

FileKey = Tuple[str, str]


@dataclass(frozen=True)
class DiskFacts:

    sizes: Dict[FileKey, int]
    total: int
    newest_mtime: Optional[float]
    dataless: bool
    unreadable: int = 0


@dataclass(frozen=True)
class ConversationVerdict:

    conversation_id: str
    on_disk: bool
    eligible: bool
    reasons: Tuple[str, ...]
    bytes: int
    files: int
    point_id: Optional[str]
    owners: Tuple[str, ...]
    newest_mtime: Optional[float]


@dataclass(frozen=True)
class SessionVerdict:

    session_uuid: str
    title: Optional[str]
    project_id: Optional[int]
    offloadable: bool
    reasons: Tuple[str, ...]
    conversations: Tuple[ConversationVerdict, ...]
    bytes: int
    idle_epoch: Optional[float]

    @property
    def shared(self) -> bool:
        return any(len(c.owners) > 1 for c in self.conversations)


def disk_facts(plan: UnitPlan) -> DiskFacts:
    sizes: Dict[FileKey, int] = {}
    newest: Optional[float] = None
    placeholder = False
    unreadable = 0
    for planned in plan.files:
        try:
            info = os.lstat(planned.path)
        except OSError as exc:
            logger.warning("offload_file_unreadable", path=str(planned.path), error=str(exc)[:200])
            unreadable += 1
            continue
        sizes[(planned.home, planned.rel)] = info.st_size
        newest = info.st_mtime if newest is None else max(newest, info.st_mtime)
        placeholder = placeholder or dataless.is_dataless_stat(info)
    return DiskFacts(sizes, sum(sizes.values()), newest, placeholder, unreadable)


def _captured_size(entry: FileEntry) -> int:
    return entry.size_seen or entry.length + entry.torn_bytes


def point_covers(manifest: Manifest, sizes: Dict[FileKey, int]) -> bool:
    held = {(e.home, e.rel): _captured_size(e) for e in manifest.files}
    return held == sizes


def session_reasons(facts: SessionFacts) -> List[str]:
    out: List[str] = []
    if facts.lifecycle == "running":
        out.append(C.REASON_LIVE)
    elif facts.lifecycle != "stopped":
        out.append(C.REASON_UNKNOWN_STATE)
    if facts.asleep:
        out.append(C.REASON_ASLEEP)
    if facts.host_key != "local":
        out.append(C.REASON_REMOTE)
    return out


def _ordered(reasons: Set[str]) -> Tuple[str, ...]:
    return tuple(r for r in C.REASONS if r in reasons)


class Evaluator:

    def __init__(self, snapshot: ChainSnapshot, running: RunningScan, scanner: Scanner, vault: Vault, now: float,
                 quiet_seconds: float = C.QUIET_SECONDS, blockers: Sequence[str] = ()) -> None:
        self.chains: ChainMap = build(snapshot)
        self._running: FrozenSet[str] = running.conversations
        self._scanner = scanner
        self._vault = vault
        self._now = now
        self._quiet = quiet_seconds
        self._blockers = tuple(blockers)
        self._verdicts: Dict[str, ConversationVerdict] = {}

    def _newest_point(self, conversation_id: str) -> Optional[Manifest]:
        try:
            return self._vault.manifests.newest(conversation_id)
        except ManifestError as exc:
            logger.warning("offload_point_unreadable", conversation_id=conversation_id, error=str(exc)[:200])
            return None

    def _plan(self, conversation_id: str) -> Optional[UnitPlan]:
        try:
            return self._scanner.plan_claude(conversation_id)
        except ManifestError as exc:
            logger.warning("offload_unsafe_conversation_id", conversation_id=conversation_id, error=str(exc)[:200])
            return None

    def conversation(self, conversation_id: str) -> ConversationVerdict:
        if conversation_id in self._verdicts:
            return self._verdicts[conversation_id]
        owners = tuple(sorted(self.chains.owners_of(conversation_id)))
        plan = self._plan(conversation_id)
        if plan is None:
            verdict = ConversationVerdict(conversation_id, False, False, (), 0, 0, None, owners, None)
        else:
            verdict = self._judge(conversation_id, owners, plan)
        self._verdicts[conversation_id] = verdict
        return verdict

    def _judge(self, conversation_id: str, owners: Tuple[str, ...], plan: UnitPlan) -> ConversationVerdict:
        disk = disk_facts(plan)
        reasons: Set[str] = set()
        for owner in owners:
            reasons.update(session_reasons(self.chains.sessions[owner]))
        if conversation_id in self._running:
            reasons.add(C.REASON_IN_USE)
        if disk.newest_mtime is not None and self._now - disk.newest_mtime < self._quiet:
            reasons.add(C.REASON_NOT_QUIET)
        if disk.dataless:
            reasons.add(C.REASON_DATALESS)
        if disk.unreadable:
            reasons.add(C.REASON_UNREADABLE_FILE)
        if self._blockers:
            reasons.add(C.REASON_NOT_READY)
        point = self._newest_point(conversation_id)
        if point is None:
            reasons.add(C.REASON_NO_VAULT_POINT)
        elif not point_covers(point, disk.sizes):
            reasons.add(C.REASON_VAULT_BEHIND)
        return ConversationVerdict(conversation_id, True, not reasons, _ordered(reasons), disk.total, len(disk.sizes),
                                   point.point_id if point is not None else None, owners, disk.newest_mtime)

    def session(self, session_uuid: str) -> Optional[SessionVerdict]:
        facts = self.chains.sessions.get(session_uuid)
        if facts is None:
            return None
        verdicts = tuple(self.conversation(c) for c in self.chains.chains[session_uuid])
        present = [v for v in verdicts if v.on_disk]
        reasons = {r for v in present for r in v.reasons}
        if not present:
            reasons.add(C.REASON_NOTHING_ON_DISK)
        newest = max((v.newest_mtime for v in present if v.newest_mtime is not None), default=None)
        activity = [t for t in (facts.last_active_epoch, newest) if t is not None]
        return SessionVerdict(session_uuid, facts.title, facts.project_id, bool(present) and not self._blockers and all(v.eligible for v in present), _ordered(reasons),
                              verdicts, sum(v.bytes for v in present), max(activity) if activity else None)

    def idle_days(self, idle_epoch: Optional[float]) -> Optional[float]:
        return None if idle_epoch is None else max(0.0, (self._now - idle_epoch) / C.SECONDS_PER_DAY)

    def sessions(self) -> List[SessionVerdict]:
        return [v for v in (self.session(s) for s in self.chains.sessions) if v is not None]

    def no_session(self) -> List[ConversationVerdict]:
        held = set(self.chains.owners)
        return [self.conversation(c) for c in sorted(self._scanner.conv_index()) if c not in held]

