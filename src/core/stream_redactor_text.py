
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Sequence, Tuple

import structlog

from src.core.message_model_secrets import (
    DETECTOR_PEM_PRIVATE_KEY,
    SecretFinding,
)
from src.core.stream_redactor_ansi import (
    PlainView,
    plain_view,
    redact_osc,
    star,
)
from src.core.stream_redactor_detect import (
    CONTEXT_CHARS,
    _StarredSpan,
    _carry_spans,
    _detect,
    bridged_detectors,
    _scan_windows,
    _stand_in,
)
from src.core.stream_redactor_wrap import (
    Joined,
    carries_marker,
    pending_bridge,
)

logger = structlog.get_logger()

_PEM_END_RE = re.compile(r"-----END[^\r\n]*?-----")

_KEY_BODY_RE = re.compile(r"[^A-Za-z0-9+/=]*(?:[A-Za-z0-9+/]+=*|=+)")

@dataclass(frozen=True)
class _OpenRegion:

    detector: str
    start: int


def _region_end_in(
    view: Joined, detector: str, search_from: int, source: str,
) -> Optional[int]:
    at = view.index_of(search_from)
    if detector == DETECTOR_PEM_PRIVATE_KEY:
        match = _PEM_END_RE.search(view.text, at)
        return view.source_end(match.end()) if match else None
    match = _KEY_BODY_RE.match(view.text, at)
    if match is None or match.end() == len(view.text):
        return None
    end = view.source_end(match.end())
    waiting = pending_bridge(source, len(source))
    if not match.group().endswith("=") and waiting is not None and waiting <= end:
        return None
    return end


def _region_end(
    views: List[Joined], detector: str, search_from: int, source: str,
) -> Optional[int]:
    ends = [_region_end_in(view, detector, search_from, source)
            for view in views]
    found = [end for end in ends if end is not None]
    if not found or (detector != DETECTOR_PEM_PRIVATE_KEY and None in ends):
        return None
    return max(found)


REGION_GUARD_CHARS: int = 128


WORD_HOLD_CHARS: int = 256


@dataclass(frozen=True)
class _Pass:

    text: str
    findings: List[SecretFinding]
    open_region: Optional[_OpenRegion]
    starred_spans: Tuple[_StarredSpan, ...]
    release: int
    osc_open: bool
    word_boundary: Optional[bool]
    context: str


def _process(
    raw: str,
    *,
    detectors: Optional[Tuple[str, ...]],
    open_region: Optional[_OpenRegion],
    in_osc: bool,
    tail_bytes: int,
    max_buffer: int,
    final: bool,
    hold_word: bool,
    at_word_start: bool,
    context: str = "",
    starred_spans: Tuple[_StarredSpan, ...] = (),
) -> _Pass:
    view = plain_view(raw, in_osc=in_osc)
    plain, index_map = view.text, view.index_map
    lead = len(context)
    original = context + plain
    full, standing = _stand_in(original, starred_spans)

    def scan(text: str, bridged: bool = False) -> List[SecretFinding]:
        wanted = bridged_detectors(detectors) if bridged else detectors
        return _scan_windows(text, wanted, tail_bytes) if text else []

    found = _detect(full, original, lead, scan)
    region_ranges: List[Tuple[int, int]] = []
    still_open: List[Tuple[str, int]] = []

    if open_region is not None:
        anchor = lead + bisect.bisect_left(index_map, open_region.start)
        end = _region_end(found.joined, open_region.detector, anchor, full)
        if end is None:
            still_open.append((open_region.detector, anchor))
        else:
            region_ranges.append((anchor, end))

    for detector, start, header_end in found.regions:
        end = _region_end(found.joined, detector, header_end, full)
        if end is not None and end <= lead:
            continue
        start = max(start, lead)
        if end is None:
            still_open.append((detector, start))
            region_ranges.append((start, header_end))
        else:
            region_ranges.append((start, end))

    release = _release_point(
        raw, view,
        tail_bytes=tail_bytes,
        max_buffer=max_buffer,
        region_open=bool(still_open),
        final=final,
        hold_word=hold_word,
        at_word_start=at_word_start,
        read=original,
        lead=lead,
        bridged=[view.removed for view in found.joined],
    )
    plain_release = bisect.bisect_left(index_map, release)
    boundary = plain[plain_release - 1].isspace() if plain_release else None

    region: Optional[_OpenRegion] = None
    if still_open:
        detector, anchor = min(still_open, key=lambda item: item[1])
        region_ranges.append((anchor, lead + plain_release))
        at = anchor - lead
        raw_start = index_map[at] if at < len(index_map) else release
        region = _OpenRegion(detector=detector, start=max(0, raw_start - release))

    cut = view.osc_payload_at
    osc_open = cut is not None and release > cut
    spans = found.spans + [(start, end, frozenset()) for start, end in region_ranges]
    findings = found.findings
    text = raw
    if spans or view.osc or osc_open:
        chars = list(raw)
        for start, end, skip in spans:
            for position in range(max(lead, start), min(end, len(full))):
                if position not in skip:
                    raw_at = index_map[position - lead]
                    star(chars, raw_at, raw_at + 1)
        for span in view.osc:
            findings = findings + redact_osc(chars, span, scan)
        if osc_open and cut is not None:
            star(chars, cut, release)
        text = "".join(chars)
    out_plain = "".join(text[index_map[p]] for p in range(
        max(0, plain_release - CONTEXT_CHARS), plain_release))
    next_context = (context + out_plain)[-CONTEXT_CHARS:]
    return _Pass(
        text, findings, region,
        _carry_spans(full, found.spans + [
            carried for carried in standing
            if not any(carried[0] < end and start < carried[1]
                       for start, end, _ in found.spans)
        ], len(next_context) - lead - plain_release),
        release, osc_open, boundary, next_context,
    )


def _word_start(text: str, stop: int, bridged: FrozenSet[int]) -> int:
    while stop and (not text[stop - 1].isspace() or stop - 1 in bridged):
        stop -= 1
    return stop


def _outside_escape(view: PlainView, release: int, *, forward: bool) -> int:
    at = bisect.bisect_left(view.escapes, (release,)) - 1
    if at >= 0:
        start, end = view.escapes[at]
        if start < release < end:
            return end if forward else start
    return release


def _release_point(
    raw: str,
    view: PlainView,
    *,
    tail_bytes: int,
    max_buffer: int,
    region_open: bool,
    final: bool,
    hold_word: bool,
    at_word_start: bool,
    read: str = "",
    lead: int = 0,
    bridged: Sequence[FrozenSet[int]] = (frozenset(),),
) -> int:
    held = len(raw)
    index_map = view.index_map
    if final:
        if not hold_word:
            return held
        release = view.pending
        text = read or view.text
        loose = bridged[0]
        stop = _word_start(text, len(text), loose)
        pending = pending_bridge(text, stop)
        if pending is not None:
            head = _word_start(text, pending, loose)
            if any(carries_marker(text, head, pending, reading)
                   for reading in bridged):
                stop = head
        begins_here = stop > 0 or at_word_start
        size = sum(1 for q in range(stop, len(text)) if q not in loose)
        held_from = max(0, stop - lead)
        if begins_here and 0 < size <= WORD_HOLD_CHARS and held_from < len(index_map):
            release = min(release, index_map[held_from])
        return release

    release = _outside_escape(
        view, min(max(0, held - tail_bytes), view.pending), forward=False)
    if region_open and index_map:
        guarded = max(
            0, bisect.bisect_left(index_map, release) - REGION_GUARD_CHARS
        )
        release = index_map[guarded] if guarded < len(index_map) else release

    if held - release > max_buffer:
        forced = held - max_buffer
        logger.warning(
            "stream_redactor_buffer_bound",
            held=held,
            natural_release=release,
            forced_release=forced,
            max_buffer=max_buffer,
            region_open=region_open,
        )
        release = _outside_escape(view, forced, forward=True)
    return release
