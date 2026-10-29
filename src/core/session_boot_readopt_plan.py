
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.core.db_models import (
    SESSION_FAMILY_SOURCE_FINGERPRINT,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
)
from src.models import Session, SessionStatus


CLAIMABLE_ORIGINS: Tuple[str, ...] = (
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_ADOPTED,
)

ID_SOURCE_HOOK_TOKEN = "hook_token"
ID_SOURCE_LEGACY_ROW = "legacy_row"
ID_SOURCE_DERIVED = "derived"

SKIP_ALREADY_HELD = "already_held"
SKIP_NO_ROW = "no_row"
SKIP_NOT_CLAIMABLE_ORIGIN = "not_claimable_origin"
SKIP_NO_EPOCH = "no_epoch"

READOPT_RAN = "ran"
READOPT_CANNOT_DETERMINE = "cannot_determine"

ADOPTED_ID_PREFIX = "adopted:"


def derived_id_for(name: str) -> str:
    return f"{ADOPTED_ID_PREFIX}{name}"


@dataclass(frozen=True)
class ReadoptTarget:

    name: str
    epoch: int
    session_id: str
    id_source: str
    working_dir: str
    agent_type: Optional[str] = None
    via_fingerprint: bool = False
    origin: str = SESSION_ORIGIN_CREATED


@dataclass(frozen=True)
class ReadoptPlan:

    targets: List[ReadoptTarget] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)

    def skipped_for(self, reason: str) -> List[str]:
        return [name for name, why in self.skipped if why == reason]


@dataclass(frozen=True)
class ReadoptReport:

    outcome: str
    held: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    plan: Optional[ReadoptPlan] = None
    detail: Optional[str] = None


def resolve_session_id(
    name: str,
    row: Dict[str, Any],
    hook_names: Dict[str, str],
) -> Tuple[str, str]:
    candidates = sorted(
        sid for sid, mapped in hook_names.items() if mapped == name and sid
    )
    if candidates:
        preferred = [
            sid for sid in candidates if not sid.startswith(ADOPTED_ID_PREFIX)
        ]
        return (preferred or candidates)[0], ID_SOURCE_HOOK_TOKEN

    legacy = row.get("legacy_session_id")
    if legacy:
        return str(legacy), ID_SOURCE_LEGACY_ROW

    return derived_id_for(name), ID_SOURCE_DERIVED


def plan_readopt(
    *,
    listing_rows: Sequence[Dict[str, Any]],
    row_lookup: Callable[[str, Optional[int]], Optional[Dict[str, Any]]],
    hook_names: Dict[str, str],
    held_ids: Sequence[str],
    held_names: Sequence[str],
    default_working_dir: str,
) -> ReadoptPlan:
    held_id_set = set(held_ids)
    held_name_set = set(held_names)
    targets: List[ReadoptTarget] = []
    skipped: List[Tuple[str, str]] = []

    for listing_row in listing_rows:
        name = listing_row.get("name")
        if not name:
            continue
        if name in held_name_set:
            skipped.append((name, SKIP_ALREADY_HELD))
            continue

        raw_epoch = listing_row.get("created_at_epoch")
        try:
            epoch = int(raw_epoch)
        except (TypeError, ValueError):
            skipped.append((name, SKIP_NO_EPOCH))
            continue

        row = row_lookup(name, epoch)
        if row is None:
            skipped.append((name, SKIP_NO_ROW))
            continue

        origin = str(row.get("origin") or "")
        if origin not in CLAIMABLE_ORIGINS:
            skipped.append((name, SKIP_NOT_CLAIMABLE_ORIGIN))
            continue

        session_id, id_source = resolve_session_id(name, row, hook_names)
        if session_id in held_id_set:
            skipped.append((name, SKIP_ALREADY_HELD))
            continue

        working_dir = (
            row.get("working_dir")
            or listing_row.get("working_dir")
            or default_working_dir
        )
        targets.append(
            ReadoptTarget(
                name=name,
                epoch=epoch,
                session_id=session_id,
                id_source=id_source,
                working_dir=str(working_dir),
                agent_type=row.get("agent_type"),
                via_fingerprint=(
                    row.get("agent_family_source")
                    == SESSION_FAMILY_SOURCE_FINGERPRINT
                ),
                origin=origin,
            )
        )
        held_id_set.add(session_id)
        held_name_set.add(name)

    return ReadoptPlan(targets=targets, skipped=skipped)


def session_for(target: ReadoptTarget) -> Session:
    born = datetime.fromtimestamp(target.epoch, tz=timezone.utc)
    return Session(
        id=target.session_id,
        working_dir=target.working_dir,
        status=SessionStatus.RUNNING,
        created_at=born,
        last_activity=born,
        agent_type=target.agent_type,
        agent_type_via_fingerprint=target.via_fingerprint,
        tmux_session=target.name,
    )


