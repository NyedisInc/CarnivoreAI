
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Optional, Sequence

import structlog

from src.core.pack.skills import alerts, push, receiver, rules
from src.core.pack.skills.doc import Choices
from src.core.pack.skills.runtime import PeerView
from src.core.pack.skills.scan import RootScan, SkillScan, scan_skill
from src.core.pack.skills.targets import SkillRoot
from src.core.skills.digest import MODE_EXECUTABLE
from src.core.skills.install_by_reference import reason_for
from src.core.skills.targets import move_to_trash

logger = structlog.get_logger()

INVENTORY_PATH = "/federation/pack/skills/inventory"
TOKEN_TTL_SECONDS = 600.0
MAX_TOKENS = 16
MAX_INVENTORY_ROWS = rules.MAX_INVENTORY_ROWS
PARTIAL = "partial"
OLDER, OFFLINE = "older carnivore", "offline"
INVENTORY_REFUSED = {"alpha_one_way": "alpha is one way here", "not_alpha": "alpha differs"}

Pair = tuple[str, str]
InventoryRow = tuple[str, str, str, str, bool]


@dataclass(frozen=True)
class Inventory:

    peer_id: str
    label: str
    state: str
    rows: tuple[InventoryRow, ...] = ()
    warez: tuple[tuple[str, str, str, str], ...] = ()
    conflicts: tuple[tuple[str, str, str], ...] = ()




def with_mode(mode: str, include: Sequence[Sequence[str]], exclude: Sequence[Sequence[str]]) -> Choices:
    return Choices(mode=mode, include=frozenset((a, b) for a, b in include), exclude=frozenset((a, b) for a, b in exclude))


def with_skill(choices: Choices, family: str, name: str, synced: bool) -> Choices:
    pair = (family, name)
    if choices.mode == "all":
        exclude = choices.exclude - {pair} if synced else choices.exclude | {pair}
        return Choices("all", choices.include, frozenset(exclude))
    include = choices.include | {pair} if synced else choices.include - {pair}
    return Choices("some" if (synced or choices.mode == "some") else "off", frozenset(include), choices.exclude)


def choices_json(choices: Choices) -> dict[str, Any]:
    return {"mode": choices.mode, "include": sorted([list(p) for p in choices.include]),
            "exclude": sorted([list(p) for p in choices.exclude])}




def _clean_rows(answer: Any) -> tuple[InventoryRow, ...]:
    rows = answer.get("skills") if isinstance(answer, dict) else None
    out: list[InventoryRow] = []
    for r in rows[:MAX_INVENTORY_ROWS] if isinstance(rows, list) else []:
        if isinstance(r, list) and len(r) == 5 and r[0] in rules.FAMILIES and all(isinstance(x, str) for x in r[1:4]) and isinstance(r[4], bool):
            out.append((r[0], r[1], r[2], r[3], r[4]))
    return tuple(sorted(out))


def _clean_lists(answer: Any, key: str, width: int) -> tuple[tuple[str, ...], ...]:
    rows = answer.get(key) if isinstance(answer, dict) else None
    out = [tuple(r) for r in (rows[:rules.MAX_SKILLS] if isinstance(rows, list) else [])
           if isinstance(r, list) and len(r) == width and all(isinstance(x, str) for x in r) and r[0] in rules.FAMILIES]
    return tuple(sorted(out))


async def fetch_inventories(views: Sequence[PeerView], request_for: Callable[[str], Any]) -> list[Inventory]:
    out: list[Inventory] = []
    for view in views:
        request = request_for(view.peer_id) if (view.has_cap() and view.up) else None
        if not view.has_cap() or request is None:
            out.append(Inventory(view.peer_id, view.label, OLDER if not view.has_cap() else OFFLINE))
            continue
        try:
            status, answer = await request("GET", INVENTORY_PATH)
        except push.WIRE_ERRORS as exc:
            logger.info("pack_skills_inventory_failed", error=type(exc).__name__)
            out.append(Inventory(view.peer_id, view.label, "failed"))
            continue
        if status == 200:
            cut = isinstance(answer, dict) and answer.get("truncated") is True
            out.append(Inventory(view.peer_id, view.label, PARTIAL if cut else "ok", _clean_rows(answer), _clean_lists(answer, "warez", 4),
                                 _clean_lists(answer, "conflicts", 3)))
        else:
            code = push._detail_code(answer)
            out.append(Inventory(view.peer_id, view.label, INVENTORY_REFUSED.get(code, "failed")))
    return out


def fingerprint(action: Mapping[str, Any], inventories: Sequence[Inventory]) -> str:
    body = {"action": action, "inventories": [[i.peer_id, i.state, [list(r) for r in i.rows], [list(r) for r in i.warez], [list(r) for r in i.conflicts]] for i in sorted(inventories, key=lambda i: i.peer_id)]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class PlanTokens:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock, self._items = clock, {}

    def clear(self) -> None:
        self._items.clear()

    def issue(self, fp: str) -> str:
        now = self._clock()
        self._items = {t: v for t, v in self._items.items() if v[1] > now}
        while len(self._items) >= MAX_TOKENS:
            self._items.pop(next(iter(self._items)))
        token = secrets.token_urlsafe(18)
        self._items[token] = (fp, now + TOKEN_TTL_SECONDS)
        return token

    def redeem(self, token: Optional[str], fp: str) -> bool:
        item = self._items.pop(token, None) if token else None
        return item is not None and item[1] > self._clock() and secrets.compare_digest(item[0], fp)




def scripts_of(skill: SkillScan) -> list[str]:
    return [f.path for f in skill.files if f.mode == MODE_EXECUTABLE]


def _ref_word(entry: Sequence[str], inv: Inventory) -> tuple[str, str]:
    family, folder, item, _kind, version = entry[0], entry[1], entry[2], entry[3], entry[4]
    theirs = [w for w in inv.warez if (w[0], w[1]) == (family, folder)]
    if theirs and all(w[2] == item and w[3] == version for w in theirs):
        return "already the same", "same"
    if theirs and all(w[2] == item for w in theirs):
        return f"will change {item} to {version}", "replace"
    if theirs:
        return f"conflict: {reason_for("other_item_there")}", "conflict"
    mine = [r for r in inv.rows if (r[0], r[1]) == (family, folder)]
    if any(r[4] for r in mine):
        return f"conflict: {reason_for("orphan_record_there")}", "conflict"
    if mine:
        return "will replace a different copy (kept 14 days in the catalog trash)", "replace"
    return f"will install {item} {version} from warez", "add"


def preview(choices: Choices, scans: Mapping[str, RootScan], inventories: Sequence[Inventory],
            refs: Sequence[Sequence[str]] = (), catalog_pairs: Collection[Pair] = (),
            focus: Optional[Collection[Pair]] = None) -> dict[str, Any]:
    chosen: list[tuple[str, str, SkillScan]] = [(f, n, s) for f in sorted(scans) for n, s in sorted(scans[f].skills.items())
                                                  if choices.selects(f, n) and (f, n) not in catalog_pairs]
    chosen_refs = [e for e in refs if len(e) == 7 and choices.selects(e[0], e[1])]
    others: set[str] = set()
    if focus is not None:
        wanted = set(focus)
        others = ({n for f, n, _ in chosen} | {e[1] for e in chosen_refs}) - {n for _, n in wanted}
        chosen = [c for c in chosen if (c[0], c[1]) in wanted]
        chosen_refs = [e for e in chosen_refs if (e[0], e[1]) in wanted]
    skills = [{"family": f, "name": n, "digest": s.digest, "size": sum(x.size for x in s.files), "files": len(s.files),
               "scripts": scripts_of(s), "problem": s.problem} for f, n, s in chosen]
    skills += [{"family": e[0], "name": e[1], "digest": e[5], "size": 0, "files": 0, "scripts": [], "problem": "", "warez": True,
                "item": e[2], "version": e[4]} for e in chosen_refs]
    computers = []
    for inv in inventories:
        counts = {"add": 0, "replace": 0, "same": 0, "conflict": 0}
        words: dict[str, str] = {}
        for f, n, s in chosen:
            mine = [r for r in inv.rows if r[0] == f and r[1] == n]
            if s.problem:
                word, key = f"conflict: {s.problem}", "conflict"
            elif any(r[4] for r in mine):
                word, key = f"conflict: {receiver.REASON_WAREZ}", "conflict"
            elif not mine:
                word, key = "will add", "add"
            elif all(r[3] == s.digest for r in mine):
                word, key = "already the same", "same"
            else:
                word, key = "will replace a different copy (kept in its skills trash 14 days)", "replace"
            if inv.state == "ok":
                counts[key] += 1
                words[f"{f}/{n}"] = word
        for e in chosen_refs:
            word, key = _ref_word(e, inv)
            if inv.state == "ok":
                counts[key] += 1
                words[f"{e[0]}/{e[1]}"] = word
        computers.append({"id": inv.peer_id, "label": inv.label, "state": inv.state, **counts, "skills": words})
    return {"skills": skills, "computers": computers, "total_bytes": sum(s["size"] for s in skills if not s["problem"]),
            "total_files": sum(s["files"] for s in skills if not s["problem"]), "others": len(others)}




def _cell(row_synced: bool, pair: Pair, digest: str, peer: Mapping[str, Any], inv: Optional[Inventory],
          ref: Optional[tuple[str, str]] = None) -> str:
    if peer["state"] in ("older carnivore", OFFLINE, "alpha is one way here", "alpha differs"):
        return peer["state"]
    if any((f, n) == pair for f, n, _ in peer["conflicts"]):
        return "conflict"
    if inv is not None and inv.state == "ok" and ref is not None:
        there = [w for w in inv.warez if (w[0], w[1]) == pair]
        if any((c[0], c[1]) == pair for c in inv.conflicts) and not (there and all((w[2], w[3]) == ref for w in there)):
            return "conflict"
        return "missing" if not there else ("in sync" if all((w[2], w[3]) == ref for w in there) else "differs")
    if inv is not None and inv.state == "ok":
        theirs = [r for r in inv.rows if (r[0], r[1]) == pair]
        if any(r[4] for r in theirs):
            return "conflict"
        if row_synced:
            return "in sync" if theirs and all(r[3] == digest for r in theirs) else ("missing" if not theirs else "differs")
        return "same" if theirs and all(r[3] == digest for r in theirs) else ("differs" if theirs else "")
    if not row_synced:
        return ""
    return peer["state"] if peer["state"] in ("syncing", "in sync") else "differs"


def matrix(sync: Any, choices: Choices, scans: Mapping[str, RootScan], inventories: Sequence[Inventory], alpha_label: str) -> dict[str, Any]:
    status, doc = sync.status(), sync.published() or {}
    synced = {(f, n): d for f, n, d in doc.get("skills", [])}
    refs = {(e[0], e[1]): (e[2], e[4]) for e in doc.get("warez", []) if len(e) == 7}
    synced.update({(e[0], e[1]): e[5] for e in doc.get("warez", []) if len(e) == 7})
    held = {(f, n): r for f, n, r in doc.get("held", [])}
    inv_by = {i.peer_id: i for i in inventories}
    pairs: dict[Pair, SkillScan | None] = {(f, n): s for f in scans for n, s in scans[f].skills.items()}
    pairs.update({p: None for p in [*held, *refs] if p not in pairs})
    for inv in inventories:
        pairs.update({(r[0], r[1]): None for r in inv.rows if (r[0], r[1]) not in pairs})
    rows = []
    for pair in sorted(pairs):
        skill = pairs[pair]
        on = choices.selects(*pair)
        digest = synced.get(pair, skill.digest if skill else "")
        state = "held" if pair in held else ("synced" if pair in synced else ("unsynced" if skill else "only elsewhere"))
        reason = held.get(pair) or (skill.problem if skill and skill.problem else "")
        cells = {pid: _cell(pair in synced, pair, digest, peer, inv_by.get(pid), refs.get(pair)) for pid, peer in status["peers"].items()}
        rows.append({"family": pair[0], "name": pair[1], "synced": on, "state": state, "reason": reason, "digest": digest, "cells": cells,
                     **({"warez": {"item": refs[pair][0], "version": refs[pair][1]}} if pair in refs else {})})
    return {"role": "alpha", "alpha": {"id": status["alpha"], "label": alpha_label}, "gen": status["gen"], "problem": status["problem"],
            "hold": status["hold"], "choices": choices_json(choices), "peers": status["peers"], "rows": rows,
            "inventory": bool(inventories)}


def receiver_view(sync: Any, alpha_id: str, alpha_label: str) -> dict[str, Any]:
    data = sync.state.load()
    doc = data.get("doc") if isinstance(data.get("doc"), dict) else {}
    placed: dict[Pair, list[str]] = {}
    placers: dict[Pair, str] = {}
    for r in data.get("applied", []):
        placed.setdefault((r.get("family"), r.get("name")), []).append(str(r.get("state")))
        if r.get("placed") is True and isinstance(r.get("alpha"), str):
            placers.setdefault((r.get("family"), r.get("name")), r["alpha"])
    rows = []
    entries = [(f, n, d, None) for f, n, d in doc.get("skills", [])] + [(e[0], e[1], e[5], e) for e in doc.get("warez", []) if len(e) == 7]
    for family, name, digest, ref in entries:
        states = placed.get((family, name), ["missing"])
        word = "in sync" if all(s == receiver.IN_SYNC for s in states) else ("conflict" if receiver.CONFLICT in states else "differs")
        row = {"family": family, "name": name, "synced": True, "state": word, "digest": digest}
        if ref is not None:
            row["warez"] = {"item": ref[2], "version": ref[4]}
        who = placers.get((family, name))
        if who:
            row["placed_by"] = {"id": who, "label": alpha_label if who == alpha_id else alerts.label_for(data, who)}
        rows.append(row)
    return {"role": "receiver", "read_only": True, "alpha": {"id": alpha_id, "label": alpha_label},
            "applied_gen": int(data.get("applied_gen") or 0), "rows": rows}




def trash_placed(state: receiver.ReceiverState, from_install_id: str, roots: Sequence[SkillRoot], stamp: Optional[str] = None,
                 services: Any = None) -> list[Pair]:
    from src.core.pack.skills import placed_warez

    stamp = stamp or f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"
    by_leaf = {(r.family, str(r.leaf)): r for r in roots}
    trashed: list[Pair] = []
    with state.lock:
        data = state.load()
        keep = []
        for row in data["applied"]:
            if row.get("alpha") != from_install_id or row.get("placed") is not True:
                keep.append(row)
                continue
            root = by_leaf.get((row.get("family"), row.get("root")))
            name = row.get("name")
            if root is None or root.problem or not isinstance(name, str) or rules.skill_name_problem(name) is not None:
                keep.append(row)
                continue
            target = Path(root.leaf) / name
            try:
                if target.is_symlink():
                    keep.append(row)
                    continue
                if row.get("item"):
                    verdict = (placed_warez.remove_mirror(row, root, target, f"{root.group}-{stamp}") if row.get("kind") == "mirror"
                               else placed_warez.remove_install(row, services))
                    if verdict == placed_warez.KEPT:
                        keep.append(row)
                    elif verdict == placed_warez.REMOVED:
                        trashed.append((root.family, name))
                elif target.exists():
                    if scan_skill(target, name).digest != row.get("digest"):
                        logger.warning("pack_skills_trash_placed_kept_edited", family=root.family)
                        keep.append(row)
                        continue
                    move_to_trash(target, root.trash, f"{root.group}-{stamp}")
                    trashed.append((root.family, name))
            except OSError as exc:
                logger.warning("pack_skills_trash_placed_failed", errno=exc.errno)
                keep.append(row)
        data["applied"] = keep
        state.save(data)
    return sorted(set(trashed))
