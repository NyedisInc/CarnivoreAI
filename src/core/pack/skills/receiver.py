
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.pack.skills import rules
from src.core.pack.skills.scan import scan_skill
from src.core.resource_push import notifier
from src.core.resource_push.topics import PACK_SKILLS
from src.core.pack.skills.targets import SkillRoot, roots_for
from src.core.skills.records import SIDECAR_NAME

logger = structlog.get_logger()

IN_SYNC, MISSING, DIFFERS, CONFLICT = "in sync", "missing", "differs", "conflict"
REASON_CASE = "name differs only by case"
REASON_WAREZ = "installed from warez there"
REASON_SKILL_LINK = "skill folder is a link"
SEEN_PER_SKILL = 32
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

Pair = tuple[str, str]


class ReceiverError(Exception):

    def __init__(self, code: str, status: int = 422, **extra: Any) -> None:
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


@dataclass(frozen=True)
class Cell:

    family: str
    name: str
    root: SkillRoot
    state: str
    reason: str = ""


class ReceiverState:

    def __init__(self, path: Path) -> None:
        self.path, self.lock = Path(path), threading.RLock()
        self.pending: Optional[dict[str, Any]] = None

    def load(self) -> dict[str, Any]:
        import json

        base: dict[str, Any] = {"v": 1, "doc": None, "applied_gen": 0, "applied": [], "seen": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return base
        except (OSError, ValueError) as exc:
            logger.warning("pack_skills_state_unreadable", error=type(exc).__name__)
            return base
        return {**base, **stored} if isinstance(stored, dict) else base

    def save(self, data: dict[str, Any]) -> bool:
        return atomic_write_json(self.path, data, log_event="pack_skills_state_write_failed")

    def applied_gen(self) -> int:
        return int(self.load().get("applied_gen") or 0)


def _pairs(rows: Any, width: int, limit: int) -> list[list[Any]]:
    if not isinstance(rows, list) or len(rows) > limit:
        raise ReceiverError("bad_document")
    out = []
    for row in rows:
        if not (isinstance(row, (list, tuple)) and len(row) >= width and row[0] in rules.FAMILIES and isinstance(row[1], str)):
            raise ReceiverError("bad_document")
        if rules.skill_name_problem(row[1]) is not None or rules.nfc(row[1]) != row[1]:
            raise ReceiverError("bad_document")
        out.append(list(row))
    return out


def validate_document(doc: Any, caller: str) -> dict[str, Any]:
    if not (isinstance(doc, dict) and doc.get("v") == 1 and doc.get("alpha") == caller and type(doc.get("gen")) is int and doc["gen"] >= 0):
        raise ReceiverError("bad_document")
    skills = _pairs(doc.get("skills", []), 3, rules.MAX_SKILLS)
    if any(not (isinstance(r[2], str) and _SHA_RE.match(r[2])) for r in skills):
        raise ReceiverError("bad_document")
    if len({(r[0], r[1]) for r in skills}) != len(skills):
        raise ReceiverError("bad_document")
    out = {"gen": doc["gen"], "alpha": caller, "skills": [[r[0], r[1], r[2]] for r in skills]}
    for key in ("removals", "unsynced"):
        rows = _pairs(doc.get(key, []), 3, rules.MAX_SKILLS * 2)
        out[key] = [[r[0], r[1], int(r[2]) if type(r[2]) is int else 0] for r in rows]
    refs = doc.get("warez", [])
    if not (isinstance(refs, list) and len(refs) <= rules.MAX_SKILLS and all(
            isinstance(r, (list, tuple)) and len(r) == 7 and all(isinstance(x, str) for x in r) and r[0] in rules.FAMILIES
            and rules.skill_name_problem(r[1]) is None and rules.nfc(r[1]) == r[1] for r in refs)):
        raise ReceiverError("bad_document")
    if len({(r[0], r[1]) for r in refs}) != len(refs) or {(r[0], r[1]) for r in refs} & {(r[0], r[1]) for r in skills}:
        raise ReceiverError("bad_document")
    out["warez"] = [list(r) for r in refs]
    raw = doc.get("choices") if isinstance(doc.get("choices"), dict) else {}
    out["choices"] = {"mode": raw.get("mode") if raw.get("mode") in ("off", "some", "all") else "off",
                      "include": [r[:2] for r in _pairs(raw.get("include", []), 2, rules.MAX_SKILLS)],
                      "exclude": [r[:2] for r in _pairs(raw.get("exclude", []), 2, rules.MAX_SKILLS)]}
    return out


def classify(root: SkillRoot, family: str, name: str, digest: str) -> Cell:
    if root.problem:
        return Cell(family, name, root, CONFLICT, root.problem)
    leaf, target = root.leaf, root.leaf / name
    try:
        if os.path.lexists(leaf):
            clash = [e for e in os.listdir(leaf) if e != name and rules.fold_key(e) == rules.fold_key(name)]
            if clash:
                return Cell(family, name, root, CONFLICT, REASON_CASE)
        if not os.path.lexists(target):
            return Cell(family, name, root, MISSING)
        if target.is_symlink():
            return Cell(family, name, root, CONFLICT, REASON_SKILL_LINK)
        if os.path.lexists(target / SIDECAR_NAME):
            return Cell(family, name, root, CONFLICT, REASON_WAREZ)
        mine = scan_skill(target, name)
    except OSError as exc:
        logger.warning("pack_skills_classify_unreadable", family=family, errno=exc.errno)
        return Cell(family, name, root, CONFLICT, "cannot read")
    return Cell(family, name, root, IN_SYNC if (mine.problem is None and mine.digest == digest) else DIFFERS)


def survey(doc: dict[str, Any], roots: Sequence[SkillRoot]) -> list[Cell]:
    cells: list[Cell] = []
    for family, name, digest in doc["skills"]:
        cells += [classify(root, family, name, digest) for root in roots_for(roots, family)]
    return cells


def need_list(cells: Sequence[Cell]) -> list[list[str]]:
    pairs = {(c.family, c.name) for c in cells if c.state in (MISSING, DIFFERS)}
    return [[f, n] for f, n in sorted(pairs)]


def forget(state: ReceiverState, names: Sequence[Sequence[Any]]) -> None:
    drop = {(r[0], r[1]) for r in names}
    if not drop:
        return
    with state.lock:
        data = state.load()
        kept = [r for r in data["applied"] if (r.get("family"), r.get("name")) not in drop]
        if len(kept) != len(data["applied"]):
            data["applied"] = kept
            state.save(data)
            notifier.notify(PACK_SKILLS)
