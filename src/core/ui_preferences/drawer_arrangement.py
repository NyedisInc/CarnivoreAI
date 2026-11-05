
from __future__ import annotations

import re
from typing import Dict, List, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION, MAX_FOLDED_SECTIONS, MAX_FOLDS, MAX_KEY_LENGTH, MAX_REMEMBERED


_RESERVED_FOLD_KEYS = frozenset(
    {"pinned", "other", "rogue", "terminals", "browsers", "files", "review", "ledger_hidden", "ledger_expanded",
     "ledger_glance", "layouts", "companies", "groups", "pack", "open", "sleeping"}
)

SECTION_IDS = ("pinned", "layouts", "groups", "companies", "rogue", "terminals", "browsers", "files", "review", "pack")

_log = structlog.get_logger(__name__)

SESSION_UUID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{0,63}$")
"""A ``sessions.session_uuid``, the same shape ``src/config/auto_sleep.py``
accepts for ``keep_awake``."""
MAX_DRAWER_ARRANGEMENT_BYTES = 262144
"""The whole field serialised; it rides every ``preferences.changed`` frame."""
_BAND_ORDER_KEYS = frozenset({"rogue", "terminals", "browsers", "files", "review"})


LAYOUT_PIN_RE = re.compile(r"^layout:[0-9A-Za-z][0-9A-Za-z-]{0,63}$")
"""A pinned saved Layout (issue #424): ``layout:<layouts.layout_uuid>``.
Accepted in ``pinned`` only; every other list holds session uuids."""

COMPANY_FOLD_RE = re.compile(r"c:(?:[0-9]{1,18}|orphaned)")
"""A company heading's fold key (issue #1338): ``c:<company id>``, or ``c:orphaned`` for the
heading of projects filed under no company. Matched with ``fullmatch`` so a trailing newline fails."""

def _pin_list(value: List[str]) -> List[str]:
    if len(value) > MAX_REMEMBERED:
        raise ValueError(f"at most {MAX_REMEMBERED} pins")
    for item in value:
        if not (SESSION_UUID_RE.match(item) or LAYOUT_PIN_RE.match(item)):
            raise ValueError("pinned holds session uuids and 'layout:<uuid>' pins only")
    return list(dict.fromkeys(value))


def _uuid_list(value: List[str], what: str) -> List[str]:
    if len(value) > MAX_REMEMBERED:
        raise ValueError(f"at most {MAX_REMEMBERED} {what}")
    for item in value:
        if not SESSION_UUID_RE.match(item):
            raise ValueError(f"{what} holds session uuids only")
    return list(dict.fromkeys(value))


def _fold_key(key: str) -> bool:
    if key in _RESERVED_FOLD_KEYS:
        return True
    if key.startswith(("g:", "p:")) and 2 < len(key) <= MAX_KEY_LENGTH:
        return True
    if key.startswith("host-off:") and 9 < len(key) <= MAX_KEY_LENGTH:
        return True
    return bool(LAYOUT_PIN_RE.match(key) or COMPANY_FOLD_RE.fullmatch(key))


def _check_folds(value: List[str]) -> List[str]:
    if len(value) > MAX_FOLDED_SECTIONS:
        raise ValueError(f"at most {MAX_FOLDED_SECTIONS} folded sections")
    for key in value:
        if not _fold_key(key):
            raise ValueError(f"unknown fold key '{key[:MAX_KEY_LENGTH]}'")
    return list(dict.fromkeys(value))


class DrawerViewState(BaseModel):
    """One device class's VIEW of the drawer (Alex (example-owner), 2026-10-10).

    Today that is the fold list alone; the phone's own folds, including the
    PROVIDERS panel's reserved ``ledger_*`` keys. See ``DrawerArrangement.mobile``.

    Attributes:
      collapsed (list[str]): folded section keys, validated by the same rule
        as ``DrawerArrangement.collapsed``.
    """

    model_config = ConfigDict(extra="forbid")

    collapsed: List[str] = Field(default_factory=list)

    @field_validator("collapsed")
    @classmethod
    def _folds(cls, value: List[str]) -> List[str]:
        return _check_folds(value)


class DrawerArrangement(BaseModel):
    """The sidebar and agents drawer arrangement, shared by every device.

    Alex (Adoom666), 2026-09-26: "pins should not be per device." Keyed by
    ``session_uuid``, never by tmux name, because a name is reused and
    changes on a reopen (CLAUDE.md, "a tmux name is not a session's identity
    in the sidebar"). The browser's own localStorage envelope stays its
    render model and offline cache; ``client/js/session-sidebar-sync.js``
    translates between the two.

    Attributes:
      v (int): the envelope version.
      pinned (list[str]): pinned session uuids and ``layout:<uuid>`` saved
        Layout pins (issue #424), one mixed list in pinned-band order.
      order (list[str]): the user's explicit order of the shared band.
      bands (dict): a group, project or kind band key (``g:<uuid>``,
        ``p:<id>``, ``rogue``, ``terminals``, ``browsers``) to that band's own
        top-to-bottom session uuids.
      collapsed (list[str]): folded section keys, validated by SHAPE as the
        client does, never against a live group list. ``layouts`` folds the
        LAYOUTS section (issue #424); it is a fold key only, never a band.
        ``layout:<uuid>`` (issue #802) is a PER-LAYOUT fold - whether one
        saved Layout's row is expanded to show its member sessions. It
        reads INVERTED from every other fold key here: since a Layout
        defaults to COLLAPSED (unlike every other section, which defaults
        open), the client stores PRESENCE to mean "the user expanded this
        one away from its default", not "collapsed" - see
        ``web/src/lib/drawer/layouts-*.ts``'s docblock.
      projects_open (bool | None): the PROJECTS super-heading's fold; None
        means never set here.
      mobile (DrawerViewState | None): the PHONE's view (Alex (example-owner),
        2026-10-10, ``docs/DECISIONS.md``). ``collapsed`` above is the DESKTOP
        fold list, the legacy meaning every older client still reads and
        writes; ``mobile.collapsed`` is the phone's. None means never split:
        the phone shows the desktop list. Pins, order and bands stay one
        shared value. ``apply_changes`` keeps the stored ``mobile`` when an
        incoming value omits the key.
      sections (list[str] | None): the user's order of the drawer's top-level
        sections, ids from ``SECTION_IDS``, no repeats (Alex (Adoom666),
        2026-10-12, #1687). ONE value for every device. None means the default
        order, which is code; a section a stored list lacks joins at its default
        slot on the client. ``apply_changes`` keeps the stored list when an
        incoming value omits the key; an explicit null clears it.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = ARRANGEMENT_SCHEMA_VERSION
    pinned: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    bands: Dict[str, List[str]] = Field(default_factory=dict)
    collapsed: List[str] = Field(default_factory=list)
    projects_open: Optional[bool] = None
    mobile: Optional[DrawerViewState] = None
    sections: Optional[List[str]] = None

    @field_validator("sections")
    @classmethod
    def _sections(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if len(value) > 2 * len(SECTION_IDS):
            raise ValueError("too many drawer sections")
        if len(set(value)) != len(value):
            raise ValueError("a drawer section is listed twice")
        known = [item for item in value if item in SECTION_IDS]
        if len(known) != len(value):
            _log.debug("drawer_arrangement.unknown_sections_dropped", dropped=len(value) - len(known))
        return known or None

    @field_validator("pinned")
    @classmethod
    def _pins(cls, value: List[str]) -> List[str]:
        return _pin_list(value)

    @field_validator("order")
    @classmethod
    def _uuids(cls, value: List[str]) -> List[str]:
        return _uuid_list(value, "remembered sessions")

    @field_validator("bands")
    @classmethod
    def _bands(cls, value: Dict[str, List[str]]) -> Dict[str, List[str]]:
        if len(value) > MAX_FOLDS:
            raise ValueError(f"at most {MAX_FOLDS} band orders")
        out: Dict[str, List[str]] = {}
        for key, uuids in value.items():
            if key in ("pinned", "other", "layouts") or not (key in _BAND_ORDER_KEYS or _fold_key(key)):
                raise ValueError(f"unknown band key '{key[:MAX_KEY_LENGTH]}'")
            out[key] = _uuid_list(uuids, "band members")
        return out

    @field_validator("collapsed")
    @classmethod
    def _folds(cls, value: List[str]) -> List[str]:
        return _check_folds(value)
