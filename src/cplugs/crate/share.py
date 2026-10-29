
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.sdk import crate_sources as cs

_IMAGE_TYPES = ("image", "document")
_SHARED = "_shared"
MAX_NESTED_JSON = 8


@dataclass
class ShareStats:

    findings: Dict[str, int] = field(default_factory=dict)
    files_changed: int = 0
    images_stripped: int = 0
    home_scrubbed: int = 0
    torn_dropped: int = 0

    def count(self, found: Dict[str, int]) -> None:
        for detector, n in found.items():
            self.findings[detector] = self.findings.get(detector, 0) + n


class ShareUnscannable(Exception):

    def __init__(self, member: str, detail: str) -> None:
        super().__init__(f"{member}: {detail}")
        self.member, self.detail = member, detail


class ShareResidualSecret(Exception):

    def __init__(self, member: str, detectors: List[str]) -> None:
        super().__init__(f"{member}: a credential survived redaction ({', '.join(detectors)})")
        self.member, self.detectors = member, detectors


@dataclass(frozen=True)
class HomeScrub:

    home: str
    enc: str

    @classmethod
    def of(cls, home: Optional[str] = None) -> "HomeScrub":
        path = str(home or Path.home()).rstrip("/")
        return cls(path, re.sub(r"[^A-Za-z0-9]", "-", path) + "-")

    def apply(self, text: str) -> Tuple[str, int]:
        target_enc = re.sub(r"[^A-Za-z0-9]", "-", K.HOME_SCRUB_TO) + "-"
        n = text.count(self.home) + text.count(self.enc)
        if n:
            text = text.replace(self.home, K.HOME_SCRUB_TO).replace(self.enc, target_enc)
        return text, n

    def found_in(self, text: str) -> bool:
        return self.home in text or self.enc in text or self.home.replace("/", "\\/") in text


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def nested_json(text: str) -> Optional[Any]:
    stripped = text.strip()
    if len(stripped) < 2 or stripped[0] not in "[{":
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _redact_value(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        out = cs.redact(value)
        inner = nested_json(out) if depth < MAX_NESTED_JSON else None
        if inner is not None:
            cleaned = _redact_value(inner, depth + 1)
            if cleaned != inner:
                return json.dumps(cleaned, ensure_ascii=False)
        return out
    if isinstance(value, list):
        return [_redact_value(v, depth) for v in value]
    if isinstance(value, dict):
        return {cs.redact(k): _redact_value(v, depth) for k, v in value.items()}
    return value


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        inner = nested_json(value) if depth < MAX_NESTED_JSON else None
        if inner is not None:
            yield from _strings(inner, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, depth)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item, depth)


_ESCAPED_QUOTE = '\\"'
_ESCAPED_BACKSLASH = "\\\\"


def _unescaped_views(text: str) -> Iterator[str]:
    for _ in range(MAX_NESTED_JSON):
        undone = text.replace(_ESCAPED_QUOTE, '"').replace(_ESCAPED_BACKSLASH, "\\")
        if undone == text:
            return
        text = undone
        yield text


def _residual(value: Any) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for text in _strings(value):
        for detector, n in cs.scan_counts(text).items():
            found[detector] = found.get(detector, 0) + n
    return found


def _transform(value: Any, scrub: HomeScrub, stats: ShareStats) -> Any:
    if isinstance(value, str):
        text, n = scrub.apply(value)
        stats.home_scrubbed += n
        return text
    if isinstance(value, list):
        return [_transform(v, scrub, stats) for v in value]
    if isinstance(value, dict):
        source = value.get("source")
        if value.get("type") in _IMAGE_TYPES and isinstance(source, dict) and source.get("type") == "base64":
            stats.images_stripped += 1
            return {"type": "text", "text": K.IMAGE_PLACEHOLDER}
        return {_transform(k, scrub, stats): _transform(v, scrub, stats) for k, v in value.items()}
    return value


def second_pass(value: Any) -> Any:
    return _redact_value(value)


def _gated(value: Any, member: str, stats: ShareStats) -> Any:
    found = _residual(value)
    if not found:
        return value
    stats.count(found)
    value = second_pass(value)
    left = _residual(value)
    if left:
        raise ShareResidualSecret(member, sorted(left))
    return value


def share_line(raw: bytes, stats: ShareStats, scrub: HomeScrub, *, member: str, number: int,
               may_be_torn: bool) -> Optional[bytes]:
    newline = raw.endswith(b"\n")
    body = raw[:-1] if newline else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ShareUnscannable(member, f"line {number} is not UTF-8") from None
    if not text.strip():
        return raw
    stats.count(cs.scan_counts(text))
    redacted = cs.redact(text)
    try:
        value, out = json.loads(redacted), redacted
    except ValueError:
        try:
            value = _redact_value(json.loads(text))
        except ValueError:
            if may_be_torn and not newline:
                stats.torn_dropped += 1
                return None
            raise ShareUnscannable(member, f"line {number} is not JSON") from None
        out = _dumps(value)
    if ('"base64"' in out) or scrub.found_in(out):
        value = _transform(value, scrub, stats)
        out = _dumps(value)
    gated = _gated(value, member, stats)
    if gated is not value:
        out = _dumps(gated)
    return out.encode("utf-8") + (b"\n" if newline else b"")


def transform_lines(lines: Iterator[bytes], stats: ShareStats, *, last_may_be_torn: bool, member: str = "",
                    home: Optional[str] = None) -> Iterator[bytes]:
    scrub = HomeScrub.of(home)
    pending: Optional[bytes] = None
    number = 0
    for line in lines:
        if pending is not None:
            number += 1
            out = share_line(pending, stats, scrub, member=member, number=number, may_be_torn=False)
            if out is not None:
                yield out
        pending = line
    if pending is not None:
        out = share_line(pending, stats, scrub, member=member, number=number + 1, may_be_torn=last_may_be_torn)
        if out is not None:
            yield out


def transform_text(data: bytes, stats: ShareStats, *, member: str = "", home: Optional[str] = None) -> Optional[bytes]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stats.count(cs.scan_counts(text))
    out, n = HomeScrub.of(home).apply(cs.redact(text))
    stats.home_scrubbed += n
    value = nested_json(out)
    if value is not None:
        gated = _gated(value, member, stats)
        return (out if gated is value else _dumps(gated)).encode("utf-8")
    found = cs.scan_counts(out)
    if found:
        stats.count(found)
        out = cs.redact(out)
        left = cs.scan_counts(out)
        if left:
            raise ShareResidualSecret(member, sorted(left))
    hidden: Dict[str, int] = {}
    for view in _unescaped_views(out):
        for detector, count in cs.scan_counts(view).items():
            hidden[detector] = hidden.get(detector, 0) + count
    if hidden:
        stats.count(hidden)
        raise ShareResidualSecret(member, sorted(hidden))
    return out.encode("utf-8")


def clean_text(text: Optional[str], member: str, home: Optional[str] = None) -> Optional[str]:
    if text is None:
        return None
    out, _n = HomeScrub.of(home).apply(cs.redact(text))
    return _gated(out, member, ShareStats())


def gate_member(member: str, value: Any) -> None:
    found = _residual(value)
    if found:
        raise ShareResidualSecret(member, sorted(found))


def shared_rel(home: str, rel: str) -> str:
    parts = rel.split("/")
    if home == "claude" and parts[0] == "projects" and len(parts) >= 3:
        return "/".join(["projects", _SHARED] + parts[2:])
    if home == "codex":
        return f"sessions/{_SHARED}/{parts[-1]}"
    return "/".join([_SHARED] + parts)
