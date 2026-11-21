
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.budget_hold.store import STORE
from src.core.budget_hold.submit_detect import SubmitDetector
from src.models.activity_status import RESTING

logger = structlog.get_logger()

_HELD_STATUSES = RESTING | {"unknown", None}

_switch_cache: Tuple[Optional[Tuple[int, int]], bool] = (None, False)


@dataclass(frozen=True)
class HoldVerdict:

    held: bool
    item_names: Tuple[str, ...] = ()
    passable: str = ""

    @property
    def item(self) -> str:
        return ", ".join(self.item_names)


def switch_on() -> bool:
    global _switch_cache
    from src.config import settings  # noqa: PLC0415

    path = Path(settings.auth_config_file).expanduser()
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("budget_hold_config_unreadable", error=str(exc))
        return True
    stamp = (st.st_mtime_ns, st.st_size)
    if _switch_cache[0] == stamp:
        return _switch_cache[1]
    try:
        argent = json.loads(path.read_text()).get("argent")
        value = bool(isinstance(argent, dict) and argent.get("enabled") is True)
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("budget_hold_config_unreadable", error=str(exc))
        return True
    _switch_cache = (stamp, value)
    return value


def _pass(data: str) -> HoldVerdict:
    return HoldVerdict(False, (), data)


def hold_check(
    session_key: Any, data: str, status: Optional[str] = None, startup_gate: Optional[str] = None,
    detector: Optional[SubmitDetector] = None, *, exempt: bool = False,
) -> HoldVerdict:
    if exempt or session_key is None or not data or not STORE.any_hold():
        return _pass(data)
    holds = STORE.holds_for(str(session_key))
    if not holds or not switch_on():
        return _pass(data)
    if status not in _HELD_STATUSES or startup_gate not in (None, "ready"):
        return _pass(data)
    prefix, submitted = (detector or SubmitDetector()).split(data)
    if not submitted:
        return _pass(data)
    return HoldVerdict(True, tuple(name for _id, name in holds), prefix)


async def live_hold_check(manager: Any, session_id: str, data: str, detector: Optional[SubmitDetector] = None) -> HoldVerdict:
    if not data or not STORE.any_hold():
        return _pass(data)
    info = await manager.get_session_info(session_id=session_id)
    if info is None:
        return _pass(data)
    return hold_check(info.session_row_id, data, info.activity_status, info.startup_gate, detector)


def raise_if_held(info: Any, *, exempt: bool = False) -> None:
    if info is None or not STORE.any_hold():
        return
    from src.core.session_one_shot_gate import BUDGET_HELD, OneShotRefused  # noqa: PLC0415

    verdict = hold_check(info.session_row_id, "\r", info.activity_status, info.startup_gate, exempt=exempt)
    if verdict.held:
        raise OneShotRefused(BUDGET_HELD, f"held: {verdict.item} is at its budget. ask the budget owner for more.")
