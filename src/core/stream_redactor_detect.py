
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional, Tuple

from src.core.message_model_secret_redaction import (
    SPAN_MARKER_RE,
    STAND_IN_BODY,
)
from src.core.message_model_secrets import (
    ALL_DETECTORS,
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_PEM_PRIVATE_KEY,
    SecretFinding,
    scan_text,
)
from src.core.stream_redactor_ansi import REDACTION_CHAR
from src.core.stream_redactor_wrap import (
    Joined,
    bridge_gaps,
    join,
    pending_bridge,
    unjoined,
)

REGION_DETECTORS: Tuple[str, ...] = (
    DETECTOR_PEM_PRIVATE_KEY,
    DETECTOR_MINISIGN_SECRET_KEY,
)


def bridged_detectors(
    detectors: Optional[Tuple[str, ...]],
) -> Tuple[str, ...]:
    return tuple(
        name for name in (ALL_DETECTORS if detectors is None else detectors)
        if name != DETECTOR_HIGH_ENTROPY_ASSIGNMENT
    )


MIN_SCAN_WINDOW: int = 2048


def _scan_windows(
    plain: str, detectors: Optional[Tuple[str, ...]], tail_bytes: int,
) -> List[SecretFinding]:
    window = max(2 * tail_bytes, MIN_SCAN_WINDOW)
    if len(plain) <= window:
        return scan_text(plain, detectors, trust_vendor_marker=True)
    step = window - tail_bytes
    seen: set[Tuple[str, int, int]] = set()
    found: List[SecretFinding] = []
    for base in range(0, len(plain), step):
        for hit in scan_text(
            plain[base:base + window], detectors, trust_vendor_marker=True,
        ):
            key = (hit.detector, base + hit.offset, hit.length)
            if key not in seen:
                seen.add(key)
                found.append(SecretFinding(
                    hit.detector, base + hit.offset, hit.length,
                    hit.value_sha256,
                ))
        if base + window >= len(plain):
            break
    found.sort(key=lambda item: item.offset)
    return found


CONTEXT_CHARS: int = 1024


@dataclass(frozen=True)
class _StarredSpan:

    marker: str
    positions: Tuple[int, ...]
    waiting: int = 0


def _stand_in(
    full: str, starred_spans: Tuple[_StarredSpan, ...],
) -> Tuple[str, List[Tuple[int, int, FrozenSet[int]]]]:
    if not starred_spans:
        return full, []
    chars = list(full)
    ranges: List[Tuple[int, int, FrozenSet[int]]] = []
    for span in starred_spans:
        first_waiting = len(span.positions) - span.waiting
        at: List[int] = []
        for index, position in enumerate(span.positions):
            if not 0 <= position < len(chars):
                continue
            at.append(position)
            if chars[position] != REDACTION_CHAR:
                continue
            if index < len(span.marker):
                chars[position] = span.marker[index]
            elif index >= first_waiting:
                chars[position] = "0"
            else:
                chars[position] = STAND_IN_BODY[
                    (index - len(span.marker)) % len(STAND_IN_BODY)]
        if at:
            ranges.append((at[0], at[-1] + 1,
                           frozenset(range(at[0], at[-1] + 1)) - frozenset(at)))
    return "".join(chars), ranges


@dataclass(frozen=True)
class _Detected:

    findings: List[SecretFinding]
    spans: List[Tuple[int, int, FrozenSet[int]]]
    regions: List[Tuple[str, int, int]]
    joined: List[Joined]


def _detect(
    text: str,
    original: str,
    lead: int,
    scan: Callable[[str, bool], List[SecretFinding]],
) -> _Detected:
    loose_gaps, tight_gaps = bridge_gaps(text)
    plain_reading = unjoined(text)
    loose = join(text, loose_gaps) if loose_gaps else plain_reading
    views = [plain_reading]
    if loose_gaps:
        views.append(loose)
        if tight_gaps != loose_gaps:
            views.append(join(text, tight_gaps))

    counted: List[SecretFinding] = []
    seen: List[Tuple[int, int]] = []
    spans: List[Tuple[int, int, FrozenSet[int]]] = []
    regions: List[Tuple[str, int, int]] = []

    def note(detector: str, start: int, end: int, digest: str) -> None:
        if any(start < s_end and s_start < end for s_start, s_end in seen):
            return
        seen.append((start, end))
        if original[start] != REDACTION_CHAR:
            counted.append(SecretFinding(detector, start, end - start, digest))

    for view in views:
        for hit in scan(view.text, view is not plain_reading):
            start, end = view.span(hit.offset, hit.length)
            if hit.detector in REGION_DETECTORS:
                if view is not plain_reading or not loose_gaps:
                    regions.append((hit.detector, start, end))
                    note(hit.detector, start, end, hit.value_sha256)
                continue
            if end <= lead:
                continue
            spans.append((start, end, view.removed))
            note(hit.detector, start, end, hit.value_sha256)
    return _Detected(counted, spans, regions, views[1:] or views)


def _carry_spans(
    text: str,
    spans: List[Tuple[int, int, FrozenSet[int]]],
    shift: int,
) -> Tuple[_StarredSpan, ...]:
    waiting = pending_bridge(text, len(text))
    carried: List[_StarredSpan] = []
    taken: List[Tuple[int, int]] = []
    for start, end, skip in sorted(spans, key=lambda span: span[0] - span[1]):
        if end + shift <= 0:
            continue
        if any(start < t_end and t_start < end for t_start, t_end in taken):
            continue
        taken.append((start, end))
        positions = [q for q in range(start, end) if q not in skip]
        head = "".join(text[q] for q in positions[:32])
        marker = SPAN_MARKER_RE.match(head)
        carried.append(_StarredSpan(
            marker.group() if marker else "",
            tuple(q + shift for q in positions),
            0 if waiting is None else sum(1 for q in positions if q >= waiting),
        ))
    return tuple(carried)
