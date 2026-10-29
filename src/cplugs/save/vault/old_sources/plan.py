"""The planner (S3): from every copy in the old sources and every copy already held, decide what to take in. PURE toward the vault: it
reads bytes through the copies' openers (prefix comparison, the first bytes for the working folder) and writes nothing.

1. Key = (family, conversation id). Versions of a key are grouped by sha256; identical bytes are one version.
2. A version that is a strict byte prefix of another is COVERED and never imported.
3. A version already in the vault or on disk is HELD (``held:*`` sources). Nothing is imported for held bytes.
4. The CURRENT copy of a conversation is its held maximal version, else its longest maximal one (``import_current``). Any other maximal
   version has diverged (lines were removed or rewritten): it is imported as a KEPT copy (``import_kept``). A version longer than a held
   one that extends it is filed kept too: it never replaces the vault's newest point.
5. Maximal versions whose folders share no encoded folder are different conversations sharing an id: each gets the unit id
   ``<id>@<first 8 hex of sha256(folder)>`` (the held one keeps the plain id). An old version never splits from a lineage that holds a held
   version: the vault's or the disk's folder is where a reorg put the conversation, so an old copy in the pre-reorg folder is a kept copy.
6. Each imported point is stamped with the source's own capture time. A kept copy is never stamped later than the unit's newest point:
   its stamp is capped one second before it, and the real time stays in the tags.
7. Sub-agent files follow the same rule per (conversation, file name) and ride inside the current point; they are never imported for a held conversation.
8. Labels (``labels.py``), the working folder and project (``attribution.py``) and the sources go in the tags.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.manifest import ManifestError, check_unit
from src.cplugs.save.vault.old_sources import containment, labels as labels_mod, model, names
from src.cplugs.save.vault.old_sources.attribution import NO_PROJECT_GROUP, Attributor, Attribution

logger = structlog.get_logger()

HEAD_BYTES = 262144
HELD_PREFIX = "held:"
HELD, COVERED, CURRENT, KEPT, SAME_AS_IMPORT = "held", "covered", "import_current", "import_kept", "same_as_import"
SKIP_PREFIX = "skip:"


@dataclass(frozen=True)
class Decision:

    source: str
    locator: str
    key: str
    decision: str
    unit: str = ""
    point_id: str = ""


@dataclass(frozen=True)
class PlannedFile:

    copy: model.Copy
    rel: str
    role: str


@dataclass
class PlannedPoint:

    unit: str
    point_id: str
    kind: str
    family: str
    enc: str
    stamp: float
    files: List[PlannedFile]
    tags: Dict[str, object]
    attribution: Attribution
    labels: Tuple[str, ...]

    @property
    def bytes(self) -> int:
        return sum(f.copy.length for f in self.files)


@dataclass
class Plan:

    points: List[PlannedPoint] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    refused: List[model.Refusal] = field(default_factory=list)
    skipped: List[model.Refusal] = field(default_factory=list)
    only_points: Optional[List[Tuple[str, str]]] = None


@dataclass
class Version:

    sha: str
    length: int
    copies: List[model.Copy]

    @property
    def held(self) -> bool:
        return any(c.source.startswith(HELD_PREFIX) for c in self.copies)

    @property
    def encs(self) -> Set[str]:
        return {c.ident.enc for c in self.copies}

    @property
    def captured(self) -> float:
        return max((c.captured_epoch for c in self.copies if not c.source.startswith(HELD_PREFIX)), default=0.0)

    def representative(self) -> model.Copy:
        old = [c for c in self.copies if not c.source.startswith(HELD_PREFIX)] or self.copies
        return sorted(old, key=lambda c: (-c.captured_epoch, c.locator))[0]


def _versions(copies: Iterable[model.Copy]) -> List[Version]:
    by_sha: Dict[str, Version] = {}
    for copy in copies:
        by_sha.setdefault(copy.sha256, Version(copy.sha256, copy.length, [])).copies.append(copy)
    return sorted(by_sha.values(), key=lambda v: v.sha)


def _lineages(maximal: List[Version]) -> List[List[Version]]:
    groups: List[List[Version]] = []
    for version in sorted(maximal, key=lambda v: (not v.held, -v.length, v.sha)):
        home = next((g for g in groups if (not version.encs - {""}) or any(version.encs & x.encs for x in g)
                     or (not version.held and any(x.held for x in g))), None)
        if home is None:
            groups.append([version])
        else:
            home.append(version)
    return groups


def _split_unit(conv: str, enc: str) -> str:
    return f"{conv}@{hashlib.sha256(enc.encode('utf-8')).hexdigest()[:8]}"


def _head(copy: model.Copy) -> bytes:
    out = b""
    for block in copy.opener():
        out += block
        if len(out) >= HEAD_BYTES:
            break
    return out[:HEAD_BYTES]


def _stamp(captured: float, cap: Optional[float]) -> float:
    value = captured if captured > 0 else (cap if cap else 1.0)
    return min(value, cap) if cap is not None else value


def plan_sources(old: Iterable[model.Copy], held: Iterable[model.Copy], book: labels_mod.LabelBook, attributor: Attributor,
                 intake: Optional[model.Intake] = None) -> Plan:
    plan = Plan(refused=list(intake.refused) if intake else [], skipped=list(intake.skipped) if intake else [])
    mains: Dict[tuple, List[model.Copy]] = {}
    subs: Dict[tuple, List[model.Copy]] = {}
    for copy in list(held) + list(old):
        if copy.ident.kind == names.KIND_MAIN:
            mains.setdefault(copy.key, []).append(copy)
        else:
            subs.setdefault((copy.ident.family, copy.ident.parent), []).append(copy)
    for key in sorted(mains):
        _plan_conversation(plan, key, mains[key], subs.pop(key, []), book, attributor)
    for key, orphans in sorted(subs.items()):
        for copy in orphans:
            if not copy.source.startswith(HELD_PREFIX):
                plan.decisions.append(Decision(copy.source, copy.locator, "/".join(key), SKIP_PREFIX + "sub_without_conversation"))
    return plan


def _skip_all(plan: Plan, version: Version, label: str, reason: str) -> None:
    for c in version.copies:
        if not c.source.startswith(HELD_PREFIX):
            plan.decisions.append(Decision(c.source, c.locator, label, SKIP_PREFIX + reason))


def _plan_conversation(plan: Plan, key: tuple, mains: List[model.Copy], sub_copies: List[model.Copy], book: labels_mod.LabelBook,
                       attributor: Attributor) -> None:
    family, conv = key
    label = f"{family}/{conv}"
    if all(c.source.startswith(HELD_PREFIX) for c in mains):
        _plan_subs(plan, conv, label, sub_copies, [])
        return
    versions = _versions(mains)
    covered = containment.covered_by([(v.sha, v.length, v.copies[0].opener) for v in versions])
    lineages = _lineages([v for v in versions if v.sha not in covered])
    held_shas = {v.sha for v in versions if v.held}
    newest_held = max((c.captured_epoch for c in mains if c.source.startswith(HELD_PREFIX)), default=0.0)
    taken: Dict[str, Set[str]] = {}
    current_points: List[PlannedPoint] = []
    for index, group in enumerate(lineages):
        unit = conv if index == 0 else _split_unit(conv, min(e for v in group for e in v.encs))
        try:
            check_unit(unit)
        except ManifestError:
            for v in group:
                _skip_all(plan, v, label, "bad_unit_id")
            continue
        held_lineage = any(v.held for v in group) or any(covered.get(sha) in {v.sha for v in group} for sha in held_shas)
        current = next((v for v in group if v.held), None) or sorted(group, key=lambda v: (-v.length, -v.captured, v.sha))[0]
        cur_stamp = _stamp(current.captured, None)
        for version in sorted(group, key=lambda v: (v is not current, v.sha)):
            if version.held:
                _decide(plan, version, label, HELD)
                continue
            is_current = version is current and not held_lineage
            cap = (newest_held - 1 if newest_held else None) if held_lineage else (None if is_current else cur_stamp - 1)
            point = _point(unit, version, "current" if is_current else "kept", _stamp(version.captured, cap), taken.setdefault(unit, set()),
                           book, attributor)
            plan.points.append(point)
            if is_current:
                current_points.append(point)
            _decide(plan, version, label, CURRENT if is_current else KEPT, unit, rep=version.representative(), point_id=point.point_id)
    for version in versions:
        if version.sha in covered:
            _decide(plan, version, label, COVERED)
    _plan_subs(plan, conv, label, sub_copies, current_points)


def _decide(plan: Plan, version: Version, label: str, decision: str, unit: str = "", rep: Optional[model.Copy] = None,
            point_id: str = "") -> None:
    for copy in version.copies:
        if copy.source.startswith(HELD_PREFIX):
            continue
        twin = rep is not None and copy is not rep
        plan.decisions.append(Decision(copy.source, copy.locator, label, SAME_AS_IMPORT if twin else decision, unit if rep else "",
                                        point_id if rep else ""))


def _point(unit: str, version: Version, kind: str, stamp: float, taken: Set[str], book: labels_mod.LabelBook, attributor: Attributor) -> PlannedPoint:
    rep = version.representative()
    ident = rep.ident
    attribution = attributor.resolve(_head(rep))
    found = book.for_conversation(ident.conv, ident.enc)
    point_id = layout.new_point_id(K.REASON_IMPORT, datetime.fromtimestamp(stamp, timezone.utc), taken)
    taken.add(point_id)
    tags: Dict[str, object] = {
        "imported": True, "kind": kind, "sources": sorted({c.source for c in version.copies if not c.source.startswith(HELD_PREFIX)}),
        "locators": sorted(c.locator for c in version.copies if not c.source.startswith(HELD_PREFIX))[:8], "original_folder": ident.enc,
        "original_working_dir": attribution.original, "captured_epoch": version.captured, "labels": list(found),
        "group": None if attribution.project_uid else NO_PROJECT_GROUP, "attribution": attribution.how}
    return PlannedPoint(unit, point_id, kind, ident.family, ident.enc, stamp, [PlannedFile(rep, ident.rel, ident.role)], tags, attribution, found)


def _plan_subs(plan: Plan, conv: str, label: str, copies: List[model.Copy], current_points: List[PlannedPoint]) -> None:
    by_name: Dict[str, List[model.Copy]] = {}
    for copy in copies:
        by_name.setdefault(copy.ident.rel.rsplit("/", 1)[-1], []).append(copy)
    for name, group in sorted(by_name.items()):
        versions = _versions(group)
        covered = containment.covered_by([(v.sha, v.length, v.copies[0].opener) for v in versions])
        filed = False
        for version in sorted((v for v in versions if v.sha not in covered), key=lambda v: (-v.length, v.sha)):
            if version.held:
                _decide(plan, version, label, HELD)
                continue
            point = next((p for p in current_points if p.enc in version.encs), current_points[0] if current_points else None)
            if point is None or filed:
                _skip_all(plan, version, label, "sub_diverged" if filed else "sub_of_held_conversation")
                continue
            rep = version.representative()
            point.files.append(PlannedFile(rep, f"projects/{point.enc}/{conv}/subagents/{name}", K.ROLE_SUBAGENT))
            _decide(plan, version, label, CURRENT, point.unit, rep=rep, point_id=point.point_id)
            filed = True
        for version in versions:
            if version.sha in covered:
                _decide(plan, version, label, COVERED)
