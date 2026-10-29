
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import structlog

from src.core.pack.skills import apply as skills_apply
from src.core.pack.skills import alerts, receiver, rules
from src.core.pack.skills.receiver import ReceiverState
from src.core.pack.skills.targets import SkillRoot, roots_for
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS, PACK_SKILLS
from src.core.skills import install_by_reference as ibr
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.core.skills.records import SIDECAR_NAME, read_sidecar
from src.core.skills.targets import remove_tree

logger = structlog.get_logger()

ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^\d{1,9}\.\d{1,9}\.\d{1,9}(?:[-+][0-9A-Za-z.+-]{1,40})?$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
KINDS = ("skill", "plugin")
MAX_ATTEMPTS = 3
MAX_CHANGES_PER_HOUR = 3
JOB_TIMEOUT_SECONDS = 300
Pair = tuple[str, str]
_RUN_LOCK = threading.Lock()


@dataclass
class Group:

    item_id: str
    folders: dict[str, str] = field(default_factory=dict)
    ref: Optional[ibr.Ref] = None
    bad: bool = False


def shape_ok(rows: Any) -> bool:
    if not isinstance(rows, list) or len(rows) > rules.MAX_SKILLS:
        return False
    return all(isinstance(r, (list, tuple)) and len(r) == 7 and all(isinstance(x, str) for x in r) and r[0] in rules.FAMILIES
               and rules.skill_name_problem(r[1]) is None and rules.nfc(r[1]) == r[1] for r in rows)


def parse(rows: Sequence[Sequence[str]]) -> dict[str, Group]:
    out: dict[str, Group] = {}
    for family, folder, item_id, kind, version, digest, body in rows:
        group = out.setdefault(item_id, Group(item_id))
        ref = ibr.Ref(item_id, kind, version, digest, body)
        good = (ITEM_RE.match(item_id) and VERSION_RE.match(version) and SHA_RE.match(digest) and SHA_RE.match(body)
                and kind in KINDS and folder == item_id.split("/", 1)[-1])
        if not good or (group.ref is not None and group.ref != ref) or family in group.folders:
            group.bad = True
        group.ref = group.ref or ref
        group.folders[family] = folder
    return out


def _real(path: Any) -> str:
    return os.path.realpath(str(path))


def _exec_paths(source: Path) -> tuple[frozenset, int]:
    execs, total = set(), 0
    for base, _dirs, files in os.walk(source):
        for name in files:
            full = Path(base) / name
            info = full.lstat()
            total += info.st_size
            if info.st_mode & 0o111 and not full.is_symlink():
                execs.add(full.relative_to(source).as_posix())
    return frozenset(execs), total


def _mirror(root: SkillRoot, name: str, source: Path, ref: ibr.Ref, data: dict[str, Any], report: skills_apply.ApplyReport,
            stamp: str) -> tuple[str, str, bool]:
    from src.core.skill_watch.measure import TooLarge
    from src.core.skill_watch.sentinel import measure_folder

    if root.problem:
        return receiver.CONFLICT, root.problem, False
    target = root.leaf / name
    if target.is_symlink():
        return receiver.CONFLICT, receiver.REASON_SKILL_LINK, False
    if target.is_dir():
        record = read_sidecar(target)
        if record is not None and f"{record.publisher}/{record.name}" != ref.item_id:
            return receiver.CONFLICT, ibr.reason_for("other_item_there"), False
        if record is not None and record.version == ref.version:
            try:
                if measure_folder(target)[0] == ref.digest:
                    return receiver.IN_SYNC, "", False
            except (TooLarge, OSError):
                pass
    execs, size = _exec_paths(source)
    problem = skills_apply._install(root, "claude", name, source, execs, size, stamp, data, report)
    return (receiver.IN_SYNC, "", True) if problem is None else (receiver.CONFLICT, problem, False)


def _purge(services: Any, ref: ibr.Ref, name: str, trashes: Sequence[Path], started: float, seen: Sequence[str]) -> list[str]:
    from src.api.catalog_views import find_item
    from src.core.skill_watch.measure import TooLarge
    from src.core.skill_watch.sentinel import measure_folder

    item, _ = find_item(services.catalog.index_cache.snapshot(), ref.item_id)
    known = {v.digest for v in item.versions} if item is not None else set()
    kept: list[str] = []
    for trash in trashes:
        try:
            entries = [e for e in trash.iterdir() if e.name.startswith(name + "-") and e.is_dir() and not e.is_symlink()
                       and e.stat().st_ctime >= started - 2]
        except OSError:
            continue
        for entry in entries:
            try:
                digest = measure_folder(entry)[0]
            except (TooLarge, OSError):
                kept.append(str(entry))
                continue
            if digest in known or digest in seen:
                remove_tree(entry)
            else:
                kept.append(str(entry))
    return kept


def _outcome_rows(group: Group, out: ibr.Outcome, ctx: "Context", data: dict[str, Any], report: skills_apply.ApplyReport,
                  stamp: str) -> list[dict[str, Any]]:
    ref, rows = group.ref, []
    catalog_dirs: dict[str, Path] = {}
    if out.install_id:
        with ctx.services.catalog.ledger() as ledger:
            catalog_dirs = {t.harness: Path(t.path) for t in ledger.targets(out.install_id)}
    previous = {(r.get("family"), r.get("root")): r for r in data["applied"] if r.get("item") == group.item_id}
    for family, folder in sorted(group.folders.items()):
        if family in out.missing_families:
            state, reason, placed = receiver.CONFLICT, ibr.reason_for("family_missing_here", family), False
        for root in roots_for(ctx.roots, family):
            base = {"family": family, "name": folder, "root": str(root.leaf), "alpha": ctx.alpha, "gen": ctx.gen, "digest": ref.digest,
                    "at": int(time.time()), "item": group.item_id, "version": ref.version}
            if family in out.missing_families:
                rows.append({**base, "state": state, "reason": reason, "placed": False})
                continue
            if out.state != ibr.IN_SYNC:
                reason = ibr.reason_for(out.code, family)
                rows.append({**base, "state": receiver.CONFLICT if out.state == ibr.CONFLICT else receiver.MISSING,
                             "reason": reason, "placed": False, "code": out.code})
                continue
            catalog_dir = catalog_dirs.get(family)
            was = previous.get((family, str(root.leaf)), {}).get("placed") is True
            if catalog_dir is not None and _real(catalog_dir.parent) == _real(root.leaf):
                rows.append({**base, "state": receiver.IN_SYNC, "reason": "", "placed": out.placed or was})
            elif family == "claude" and catalog_dir is not None:
                state, reason, placed = _mirror(root, folder, catalog_dir, ref, data, report, stamp)
                rows.append({**base, "state": state, "reason": reason, "placed": placed or (state == receiver.IN_SYNC and was),
                             "kind": "mirror"})
    return rows


@dataclass
class Context:

    state: ReceiverState
    roots: Sequence[SkillRoot]
    services: Any
    loop: Any
    alpha: str
    gen: int
    still_valid: Callable[[], bool]
    clock: Callable[[], float] = time.time


TERMINAL_FETCH_CODES = ("consent_mismatch", "digest_differs")


def _due(rec: Mapping[str, Any], gen: int, now: float, install_allowed: bool, retry_only: bool, *, gone: bool = False,
         same_ref: bool = False) -> bool:
    code = rec.get("code", "")
    if gone and rec.get("outcome") == ibr.IN_SYNC and (install_allowed or retry_only):
        return True
    if not retry_only and install_allowed and rec.get("gen") != gen and not (same_ref and code in TERMINAL_FETCH_CODES):
        return True
    return bool(code) and ibr.is_transient(code) and rec.get("attempts", 0) < MAX_ATTEMPTS and now >= rec.get("next_at", 0)


def installed_versions(services: Any) -> dict[str, str]:
    with services.catalog.ledger() as ledger:
        return {r.item_id: r.version for r in ledger.list() if r.scope == SCOPE_GLOBAL}


def inventory_rows(services: Any, applied: Sequence[Mapping[str, Any]]) -> tuple[list[list[str]], list[list[str]]]:
    warez: list[list[str]] = []
    if services is not None:
        with services.catalog.ledger() as ledger:
            for row in ledger.list():
                if row.scope == SCOPE_GLOBAL:
                    warez += [[t.harness, Path(t.path).name, row.item_id, row.version] for t in ledger.targets(row.install_id)]
    conflicts = [[r["family"], r["name"], str(r.get("code") or r.get("reason") or "conflict")[:64]] for r in applied
                 if r.get("item") and r.get("state") == receiver.CONFLICT and isinstance(r.get("family"), str) and isinstance(r.get("name"), str)]
    return sorted(warez)[:rules.MAX_SKILLS], sorted(conflicts)[:rules.MAX_SKILLS]


def running() -> bool:
    return _RUN_LOCK.locked()


def run(doc: Mapping[str, Any], ctx: Context, install: Optional[Sequence[Sequence[str]]], *, retry_only: bool = False) -> bool:
    with _RUN_LOCK:
        return _run(doc, ctx, install, retry_only=retry_only)


def _run(doc: Mapping[str, Any], ctx: Context, install: Optional[Sequence[Sequence[str]]], *, retry_only: bool = False) -> bool:
    groups = parse(doc.get("warez", []))
    allowed = {(a, b) for a, b in (install or [])}
    changed = False
    have = installed_versions(ctx.services) if ctx.services is not None else None
    with ctx.state.lock:
        data = ctx.state.load()
        if data.get("ref_hold") is not bool(groups) and doc.get("alpha") == ctx.alpha and ctx.still_valid():
            data["ref_hold"] = bool(groups)
            ctx.state.save(data)
    for item_id, group in sorted(groups.items()):
        if not ctx.still_valid():
            break
        now = ctx.clock()
        with ctx.state.lock:
            data = ctx.state.load()
            rec = data.setdefault("refs", {}).get(item_id, {})
            ok = any((f, n) in allowed for f, n in group.folders.items())
            same = (rec.get("version"), rec.get("digest"), rec.get("body")) == (group.ref.version, group.ref.digest, group.ref.body_sha)
            if not _due(rec, ctx.gen, now, ok, retry_only, gone=have is not None and have.get(item_id) != rec.get("version"), same_ref=same):
                continue
            stamp = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.urandom(2).hex()}"
            recent = [t for t in rec.get("changes", []) if now - t < 3600]
        if group.bad:
            out = ibr.Outcome(ibr.CONFLICT, "bad_entry", started=now)
        elif len(recent) >= MAX_CHANGES_PER_HOUR and rec.get("version") != group.ref.version:
            out = ibr.Outcome(ibr.CONFLICT, "keeps_changing", started=now)
        else:
            families = tuple(sorted(group.folders))
            future = asyncio.run_coroutine_threadsafe(ibr.install_exact(ctx.services, group.ref, families=families), ctx.loop)
            try:
                out = future.result(timeout=JOB_TIMEOUT_SECONDS)
            except Exception as exc:  # noqa: BLE001
                future.cancel()
                logger.warning("pack_ref_item_failed", item_id=item_id, error=type(exc).__name__)
                out = ibr.Outcome(ibr.UNKNOWN, "unknown", started=now)
                _record(ctx, group, out, recent, rec, stamp, now)
                break
        _record(ctx, group, out, recent, rec, stamp, now)
        changed = True
    return changed


def _record(ctx: Context, group: Group, out: ibr.Outcome, recent: list[float], rec: Mapping[str, Any], stamp: str, now: float) -> None:
    with ctx.state.lock:
        data = ctx.state.load()
        report = skills_apply.ApplyReport()
        rows = _outcome_rows(group, out, ctx, data, report, stamp) if ctx.services is not None else []
        kept: list[tuple[str, str]] = []
        if (out.changed or report.changed or out.state != ibr.IN_SYNC) and ctx.services is not None:
            for family, folder in sorted(group.folders.items()):
                trashes = {ctx.services.install_roots.trash_dir(family, SCOPE_GLOBAL, None)} | {r.trash for r in roots_for(ctx.roots, family)}
                seen = data["seen"].get(f"{family}/{folder}", [])
                kept += [(family, k) for k in _purge(ctx.services, group.ref, group.ref.item_id.split("/", 1)[1], sorted(trashes), out.started, seen)]
        pairs = {(f, n) for f, n in group.folders.items()}
        data["applied"] = [r for r in data["applied"] if (r.get("family"), r.get("name")) not in pairs] + rows
        attempts = (rec.get("attempts", 0) + 1) if out.retry and rec.get("code") == out.code else (1 if out.retry else 0)
        data.setdefault("refs", {})[group.item_id] = {
            "gen": ctx.gen, "version": group.ref.version, "digest": group.ref.digest, "body": group.ref.body_sha, "outcome": out.state, "code": out.code,
            "attempts": attempts, "next_at": now + ibr_backoff(attempts), "disk": out.disk,
            "changes": [*recent, now] if out.version_changed else recent, "kept": [k for _, k in kept]}
        ctx.state.save(data)
    notifier.notify(PACK_SKILLS)
    if out.changed or report.changed:
        notifier.notify(LOCAL_SKILLS)
    alerts.replaced([(f, group.folders[f], k) for f, k in kept], ctx.alpha, ctx.gen)


def ibr_backoff(attempts: int) -> float:
    from src.core.pack.skills.push import BACKOFF_SECONDS

    return BACKOFF_SECONDS[min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1] if attempts else 0.0


def reset_transient(state: ReceiverState) -> None:
    with state.lock:
        data = state.load()
        touched = False
        for rec in data.get("refs", {}).values():
            if rec.get("code") and ibr.is_transient(rec["code"]) and rec.get("attempts"):
                rec["attempts"], rec["next_at"], touched = 0, 0, True
            if rec.get("code") in TERMINAL_FETCH_CODES and rec.pop("body", None) is not None:
                touched = True
        if touched:
            state.save(data)


def clear_hold_if_alpha(state: ReceiverState, install_id: str) -> None:
    if (state.load().get("doc") or {}).get("alpha") == install_id:
        clear_hold(state)


def clear_hold(state: ReceiverState) -> None:
    with state.lock:
        data = state.load()
        if data.get("ref_hold"):
            data["ref_hold"] = False
            state.save(data)
