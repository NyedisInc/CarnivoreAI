
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Set, Tuple

import structlog

from src.core.notifications import catalog_lines, types
from src.core.notifications.contracts import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARN, NotifyEvent
from src.core.notifications.kind_specs import KindSpec
from src.core.timers.redact import redact

log = structlog.get_logger(__name__)

TEST_KIND = "test"
DETAILS_CAP = 200
SMS_SEGMENT = 160
NAME_CAP = 80
_ELLIPSIS = "..."

_PREFIX = ("notify.copy.",)
_PLUGIN_TAILS = ("notify.copy.",)
_FAMILY_SEVERITY: Dict[str, str] = {
    types.FAMILY_NEEDS_YOU: SEVERITY_WARN,
    types.FAMILY_SESSIONS: SEVERITY_INFO,
    types.FAMILY_ACCOUNTS: SEVERITY_WARN,
    types.FAMILY_HEALTH: SEVERITY_ERROR,
    types.FAMILY_APP: SEVERITY_INFO,
    types.FAMILY_IN_APP: SEVERITY_INFO,
}
_TYPE_SEVERITY: Dict[str, str] = {"session.died": SEVERITY_ERROR}

_PLACEHOLDER = re.compile(r"\{(session|project|computer|from_account|to_account|limit)\}")
_OPTIONAL = re.compile(r"\[([^\[\]]*)\]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩﻿]")
_URL = re.compile(r"(?i)\b(?:(?:https?|ftp)://|www\.)[^\s<>\"']+")
_BARE_DOT = re.compile(r"(?<=\w)(?:\.(?=[^\W\d_]{2})|[\u3002\uff0e\uff61](?=[A-Za-z]{2}))")
_IPV4 = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")
RAW_CAP = 2048

_lock = threading.Lock()
_cache: Tuple[Optional[Path], Tuple[int, ...], Dict[str, str]] = (None, (), {})
_missing_logged: Set[str] = set()
catalog_path: Path = catalog_lines.DEFAULT_CATALOG_PATH
plugins_root: Path = catalog_lines.PLUGINS_ROOT


@dataclass(frozen=True)
class Rendered:

    type_id: str
    title: str
    body: str
    details: Optional[str]
    link: Optional[str]
    severity: str
    session: str
    project: str
    computer: str


def _stamp(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -2


def _catalog() -> Dict[str, str]:
    global _cache
    path = catalog_path
    slices = catalog_lines.plugin_slice_paths(plugins_root)
    stamp = tuple(_stamp(p) for p in (path, *slices))
    with _lock:
        if _cache[0] == path and _cache[1] == stamp:
            return _cache[2]
        try:
            lines = catalog_lines.read_prefixed(_PREFIX, path)
            lines.update(catalog_lines.read_plugin_slices(_PLUGIN_TAILS, plugins_root))
        except (OSError, ValueError) as exc:
            log.warning("notify_copy_catalog_unreadable", error_type=type(exc).__name__)
            lines = _cache[2] if _cache[0] == path else {}
        _cache = (path, stamp, lines)
        return lines


def clean_text(value: str, cap: int) -> str:
    flat = " ".join(_CONTROL.sub(" ", value).split())
    return cap_text(flat, cap)


def cap_text(value: str, cap: int) -> str:
    if len(value) <= cap:
        return value
    return value[: max(cap - len(_ELLIPSIS), 0)].rstrip() + _ELLIPSIS


def defang_urls(value: str) -> str:
    def one(match: "re.Match[str]") -> str:
        url = match.group(0)
        url = re.sub(r"(?i)^(h)tt(ps?)://", lambda m: f"{m.group(1)}xx{m.group(2)}://", url)
        url = re.sub(r"(?i)^ftp://", "fxp://", url)
        return url.replace(".", "[.]")

    spaced = _IPV4.sub(lambda m: m.group(0).replace(".", "[.]"), _URL.sub(one, value))
    return _BARE_DOT.sub("[.]", spaced)


def scrub_details(text: str) -> Optional[str]:
    cleaned = defang_urls(redact(text[:RAW_CAP]))
    cleaned = clean_text(cleaned, DETAILS_CAP)
    return cleaned or None


def _line(key: str, params: Mapping[str, str]) -> str:
    template = _catalog().get(key)
    if template is None:
        with _lock:
            first = key not in _missing_logged
            _missing_logged.add(key)
        if first:
            log.warning("notify_copy_key_missing", key=key)
        return key
    if not params.get("project"):
        template = template.replace(" ({project})", "")
    if not params.get("computer"):
        template = template.replace(" on {computer}", "")
    if "[" in template:
        template = _OPTIONAL.sub(
            lambda m: m.group(1) if all(params.get(p) for p in _PLACEHOLDER.findall(m.group(1))) else "", template)
    filled = _PLACEHOLDER.sub(lambda m: params.get(m.group(1), ""), template)
    return " ".join(filled.split())


def effective_severity(event: NotifyEvent) -> str:
    if event.severity != SEVERITY_INFO:
        return event.severity
    if event.type_id in _TYPE_SEVERITY:
        return _TYPE_SEVERITY[event.type_id]
    row = types.get_type(event.type_id)
    return _FAMILY_SEVERITY.get(row.family, SEVERITY_INFO) if row else SEVERITY_INFO


def render(event: NotifyEvent, kind: KindSpec, *, details_on: bool) -> Rendered:
    def name(raw: str) -> str:
        return clean_text(defang_urls((raw or "")[:RAW_CAP]), NAME_CAP)

    session = name(event.session_ref) or "a session"
    project, computer = name(event.project), name(event.computer)
    params = {"session": session, "project": project, "computer": computer}
    params.update({key: name(value) for key, value in event.copy_fields})
    row = types.get_type(event.type_id)
    if event.kind == TEST_KIND:
        title_key, body_key = "notify.copy.test.title", "notify.copy.test.body"
    else:
        title_key = row.copy_title_key if row else f"{types.catalog_namespace(event.type_id)[1]}.title"
        body_key = row.copy_body_key if row else f"{types.catalog_namespace(event.type_id)[1]}.body"
        if row and event.copy_variant:
            title_key = f"{row.copy_prefix}.{event.copy_variant}.title"
            body_key = f"{row.copy_prefix}.{event.copy_variant}.body"
    details = None
    if details_on and kind.details_allowed and not kind.sms_like and event.details:
        details = scrub_details(event.details)
    return Rendered(
        type_id=event.type_id, title=_line(title_key, params), body=_line(body_key, params), details=details,
        link=event.link or None, severity=effective_severity(event), session=session, project=project,
        computer=computer,
    )


def plain_text(rendered: Rendered, limit: Optional[int] = None) -> str:
    parts = [rendered.title, rendered.body]
    if rendered.link:
        parts.append(rendered.link)
    if rendered.details:
        parts.append(rendered.details)
    text = "\n".join(parts)
    return cap_text(text, limit) if limit else text


def sms_text(rendered: Rendered) -> str:
    head = f"{rendered.title}: {rendered.body}"
    link = rendered.link if rendered.link and len(rendered.link) <= SMS_SEGMENT // 2 else None
    if link is None:
        return cap_text(head, SMS_SEGMENT)
    room = SMS_SEGMENT - len(link) - 1
    return cap_text(head, room) + " " + link
