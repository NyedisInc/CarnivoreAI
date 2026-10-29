
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = structlog.get_logger()

SWARM_KEY = "swarm"

LookShape = Literal["square", "circle", "hexagon", "triangle", "diamond", "pentagon", "octagon", "star", "shield", "cloud"]
LookRank = Literal["sysop", "company", "project", "agent"]
LookState = Literal[
    "working", "working_subagent", "question", "notice", "finished_unread", "idle", "dead", "unknown",
    "asleep", "startup_gate", "question_waiting", "done", "talking", "escalating", "learning", "promoted",
    "alert_routine", "alert_priority", "alert_immediate", "alert_flash",
]
LookAnimation = Literal[
    "think-orbit", "subagent-morph", "ask", "perk", "hop", "rest", "bury", "hollow",
    "sink", "knock", "lean-sway", "done-spin", "talk", "launch", "gulp", "grow",
    "bristle", "pulse", "shake", "freak", "none",
]
LOOK_MAPS = ("shapes", "animations")
CLEARABLE = ("max_children_per_parent", "max_live_bodies", "spawn_load_per_core")


class LookShapes(BaseModel):
    """The body shape each agent type wears (square for all four by default: today's look)."""

    model_config = ConfigDict(extra="forbid")

    sysop: LookShape = "square"
    company: LookShape = "square"
    project: LookShape = "square"
    agent: LookShape = "square"


class SwarmConfig(BaseModel):
    """Swarm tunables. Fields: max_children_per_parent and max_live_bodies (optional caps, unset = no cap: a new body is admitted
    by measuring the machine instead, ``admission``), spawn_load_per_core (optional override of ``admission.LOAD_PER_CORE_MAX``),
    auto_sleep_idle_minutes (10),
    hop_timeout_minutes (10), closeout_window_minutes (15: a finished task agent nobody closed out is closed out after it), closeout_default (teardown: the
    server accepts the waiting report, so the agent is torn down unless its task type earned a promotion, when it sleeps as a candidate;
    sleep: it only sleeps and its parent is carded, #1457), wake_hit_min_coverage (0.6), learning_batch_size (10), learning_max_age_hours (24),
    flash_per_agent_per_hour (1), flash_per_swarm_per_hour (3), page_default_view (tree), panel_default_density
    (expanded), character_pack (theme: follow the theme; else a pack name), upper_ranks_permissions (skip_all: SysOp,
    company and project agents launch with permission prompts off, Alex (Adoom666), 2026-10-07, #1380; or ask), and the
    Swarm look (#1426): color_mode (project: the project color families; random: a stable bright hue per agent), shapes
    (a body shape per agent type, square by default) and animations (a state's picked animation or "none"; an absent
    state plays its own), and naming_family (False: Alex (Adoom666), 2026-10-08, #1444: off means no naming-family review card and
    plain names; on, a project agent may propose a family and its spawns then need a persona name), and chat_card_bodies (False: Alex
    (Adoom666), 2026-10-27, #2590: off means a board card's body is never an entry of an agent's chat, so no agent reading its
    thread spends tokens on it, nor is a server info notice such as "wake failed", #1553; on shows each board card in the chat of
    the thread that holds its list, and the notices, as before)."""

    model_config = ConfigDict(extra="forbid")

    max_children_per_parent: Optional[int] = Field(None, ge=1, le=50)
    max_live_bodies: Optional[int] = Field(None, ge=1, le=200)
    spawn_load_per_core: Optional[float] = Field(None, ge=0.25, le=16.0)
    auto_sleep_idle_minutes: int = Field(10, ge=1, le=1440)
    hop_timeout_minutes: int = Field(10, ge=1, le=1440)
    closeout_window_minutes: int = Field(15, ge=1, le=1440)
    closeout_default: Literal["teardown", "sleep"] = "teardown"
    wake_hit_min_coverage: float = Field(0.6, ge=0.0, le=1.0)
    learning_batch_size: int = Field(10, ge=1, le=200)
    learning_max_age_hours: int = Field(24, ge=1, le=720)
    flash_per_agent_per_hour: int = Field(1, ge=1, le=20)
    flash_per_swarm_per_hour: int = Field(3, ge=1, le=60)
    page_default_view: Literal["tree", "org", "squares"] = "tree"
    panel_default_density: Literal["condensed", "expanded", "detailed"] = "expanded"
    character_pack: str = Field("theme", pattern=r"^[a-z0-9_-]{1,40}$")
    upper_ranks_permissions: Literal["skip_all", "ask"] = "skip_all"
    color_mode: Literal["project", "random"] = "project"
    shapes: LookShapes = Field(default_factory=LookShapes)
    animations: Dict[LookState, LookAnimation] = Field(default_factory=dict)
    naming_family: bool = False
    chat_card_bodies: bool = False


def read_block(config: Dict[str, Any]) -> SwarmConfig:
    block = config.get(SWARM_KEY)
    if block is None:
        return SwarmConfig()
    if not isinstance(block, dict):
        logger.warning("invalid_swarm_block", reason="not_an_object")
        return SwarmConfig()
    try:
        return SwarmConfig(**block)
    except (TypeError, ValidationError) as exc:
        logger.warning("invalid_swarm_block", reason=type(exc).__name__)
        return SwarmConfig()


def read_current() -> SwarmConfig:
    import json
    from pathlib import Path

    from src.config import settings as app_settings

    try:
        data = json.loads(Path(app_settings.auth_config_file).expanduser().read_text())
    except (OSError, ValueError) as exc:
        logger.warning("swarm_config_unreadable", error_type=type(exc).__name__)
        return SwarmConfig()
    return read_block(data) if isinstance(data, dict) else SwarmConfig()


def write_changes(config_path: Path, changes: Dict[str, Any]) -> SwarmConfig:
    from src.core import config_writer

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        current = read_block(doc).model_dump()
        merged_changes = {k: ({**current[k], **v} if k in LOOK_MAPS and isinstance(v, dict) else v) for k, v in changes.items()}
        merged = SwarmConfig(**{**current, **merged_changes})
        return {**doc, SWARM_KEY: merged.model_dump()}

    return read_block(config_writer.commit(config_path, mutate).data)


def naming_family_on() -> bool:
    return read_current().naming_family
