
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

import structlog

logger = structlog.get_logger()

CHOICE_ACCEPTED: str = "accepted"

CHOICE_UNKNOWN: str = "unknown"

CHOICE_CANNOT_DETERMINE: str = "cannot_determine"

ALL_CHOICE_VERDICTS: frozenset = frozenset(
    {CHOICE_ACCEPTED, CHOICE_UNKNOWN, CHOICE_CANNOT_DETERMINE}
)


@dataclass(frozen=True)
class AgentChoice:

    verdict: str
    agent_type: str = ""
    command: Optional[str] = None
    available: tuple = ()
    detail: str = ""

    @property
    def accepted(self) -> bool:
        return self.verdict == CHOICE_ACCEPTED


def configured_wrapper_ids(settings_obj) -> Optional[List[str]]:
    try:
        agents = settings_obj.load_auth_config().agents
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("agent_choice_config_unreadable", error=str(exc))
        return None
    wrappers = getattr(agents, "wrappers", None)
    if wrappers is None:
        return None
    return [str(w.id) for w in wrappers]


def validate_agent_choice(
    settings_obj,
    agent_type: Optional[str],
    *,
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> AgentChoice:
    asked = (agent_type or "").strip()
    if not asked:
        return AgentChoice(
            verdict=CHOICE_CANNOT_DETERMINE,
            detail="no agent was named, so there was nothing to check",
        )

    ids = configured_wrapper_ids(settings_obj)
    if ids is None:
        return AgentChoice(
            verdict=CHOICE_CANNOT_DETERMINE,
            agent_type=asked,
            detail=(
                "the launch wrapper list could not be read, so whether "
                f"'{asked}' is configured cannot be determined"
            ),
        )

    if asked not in ids:
        return AgentChoice(
            verdict=CHOICE_UNKNOWN,
            agent_type=asked,
            available=tuple(ids),
            detail=(
                f"'{asked}' is not a configured launch wrapper; this "
                f"install has {', '.join(ids) if ids else 'none'}"
            ),
        )

    try:
        command = settings_obj.pane_launch_command(
            asked, model=model, extra_args=extra_args
        )
    except (ValueError, OSError, AttributeError) as exc:
        logger.warning(
            "agent_choice_command_unresolved", agent_type=asked, error=str(exc)
        )
        return AgentChoice(
            verdict=CHOICE_CANNOT_DETERMINE,
            agent_type=asked,
            available=tuple(ids),
            detail=f"'{asked}' could not be turned into a command: {exc}",
        )

    if not (command or "").strip():
        return AgentChoice(
            verdict=CHOICE_CANNOT_DETERMINE,
            agent_type=asked,
            available=tuple(ids),
            detail=f"'{asked}' resolved to an empty command, so it was not run",
        )

    return AgentChoice(
        verdict=CHOICE_ACCEPTED,
        agent_type=asked,
        command=command,
        available=tuple(ids),
        detail=f"restarting with {asked}",
    )


def resolve_wrapper_offers(
    settings_obj,
    *,
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
):
    from src.core.session_restart_preview import WrapperOffer

    ids = configured_wrapper_ids(settings_obj)
    if ids is None:
        return None
    try:
        wrappers = settings_obj.load_auth_config().agents.wrappers
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("agent_choice_offers_unreadable", error=str(exc))
        return None

    offers = []
    for wrapper in wrappers:
        command = None
        reason = ""
        try:
            command = settings_obj.pane_launch_command(
                wrapper.id, model=model, extra_args=extra_args
            )
        except (ValueError, OSError, AttributeError) as exc:
            reason = str(exc)
        offers.append(
            WrapperOffer(
                agent_type=str(wrapper.id),
                label=str(getattr(wrapper, "label", "") or wrapper.id),
                command=command,
                unavailable_reason=reason,
                family=str(getattr(wrapper, "family", "") or ""),
                icon=getattr(wrapper, "icon", None) or None,
            )
        )
    return offers


def persist_agent_type(
    conn: sqlite3.Connection, *, socket: str, tmux_name: str, agent_type: str
) -> bool:
    from src.core.agent_family_display import resolve_family_for_display
    from src.core.db_models import SESSION_FAMILY_SOURCE_LAUNCHED
    from src.config import wrapper_reader
    from src.core.session_store import identity_for_live_name

    row = identity_for_live_name(conn, socket=socket, name=tmux_name)
    if row is None:
        logger.info(
            "agent_choice_not_persisted_no_row",
            tmux_name=tmux_name,
            socket=socket,
            agent_type=agent_type,
        )
        return False

    family, _source = resolve_family_for_display(agent_type, wrapper_reader.configured_wrappers())
    agent_family = family.name if family else None

    conn.execute(
        "UPDATE sessions SET agent_type = ?, agent_family = ?, "
        "agent_family_source = ? WHERE id = ?",
        (agent_type, agent_family, SESSION_FAMILY_SOURCE_LAUNCHED, int(row["id"])),
    )
    conn.commit()
    logger.info(
        "agent_choice_persisted",
        session_row_id=int(row["id"]),
        tmux_name=tmux_name,
        agent_type=agent_type,
        agent_family=agent_family,
        was=row.get("agent_type"),
    )
    return True
