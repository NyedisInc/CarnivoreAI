
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.pack.globalsync import rules, scrub

logger = structlog.get_logger()

KEEP_BACKUPS = 5
_CLAUDE_RELAY_RE = re.compile(r"^[0-9a-f]{12}-[a-z0-9][a-z0-9-]{0,62}-relay$")
_CODEX_RELAY_RE = re.compile(r"^[0-9a-f]{12}-[a-z0-9][a-z0-9-]{0,62}-relay-codex$")


class ApplyError(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Report:

    written: int = 0
    unchanged: int = 0
    removed: int = 0
    refused: List[List[str]] = field(default_factory=list)
    folders: int = 0
    backup: Optional[str] = None
    targets: List[Tuple[Path, List[str]]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {"written": self.written, "unchanged": self.unchanged, "removed": self.removed, "folders": self.folders,
                "refused": self.refused[:rules.MAX_REFUSALS_KEPT], "refused_total": len(self.refused), "backup": self.backup}


def targets_for(slot: str, home: Path, accounts_root: Path, accounts: Iterable[Any]) -> List[Path]:
    kind, name = slot.split(".", 1)
    if name != "default":
        found = [a for a in accounts if a.id == name and a.provider == kind]
        if not found:
            return []
        folder = found[0].claude_config_dir if kind == "claude" else found[0].codex_home
        return [Path(os.path.expanduser(folder))] if folder else []
    base = {"claude": home / ".claude", "codex": home / ".codex", "agents": home / ".agents", "agy": home / ".gemini" / "config"}[kind]
    out = [base]
    pattern = _CLAUDE_RELAY_RE if kind == "claude" else _CODEX_RELAY_RE if kind == "codex" else None
    if pattern is not None:
        try:
            with os.scandir(accounts_root) as it:
                out += [Path(e.path) for e in sorted(it, key=lambda e: e.name) if pattern.match(e.name) and e.is_dir(follow_symlinks=False)]
        except OSError:
            pass
    return out


class State:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, List[str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: [x for x in v if isinstance(x, str)] for k, v in raw.get("written", {}).items() if isinstance(v, list)} if isinstance(raw, dict) else {}

    def save(self, written: Dict[str, List[str]]) -> bool:
        return atomic_write_json(self.path, {"v": 1, "written": written}, log_event="pack_global_state_write_failed")


def _stage(bundle: Path, stage: Path, wanted: Set[str]) -> List[Tuple[str, str, Path, int]]:
    out: List[Tuple[str, str, Path, int]] = []
    total = 0
    try:
        with tarfile.open(bundle, "r:gz") as tar:
            for member in tar:
                if len(out) >= rules.MAX_FILES:
                    raise ApplyError("too_many_files")
                if not member.isreg() or member.size > rules.MAX_FILE_BYTES:
                    continue
                slot, _, rel = member.name.partition("/")
                if not rules.SLOT_RE.match(slot) or slot.split(".")[0] not in wanted or rules.path_problem(slot.split(".")[0], rel):
                    continue
                total += member.size
                if total > rules.MAX_TOTAL_BYTES:
                    raise ApplyError("too_large")
                source = tar.extractfile(member)
                if source is None:
                    continue
                path = stage / f"{len(out):07d}"
                with open(path, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                out.append((slot, rel, path, member.mode & 0o755 | 0o600))
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ApplyError("bad_bundle") from exc
    return out


def _clear_path(target: Path, rel: str, checked: Set[str]) -> Optional[str]:
    cur = target
    for part in rel.split("/")[:-1]:
        cur = cur / part
        if str(cur) in checked:
            continue
        if os.path.islink(cur) or (os.path.lexists(cur) and not cur.is_dir()):
            return rules.REASON_LINK
        checked.add(str(cur))
    dest = target / rel
    return rules.REASON_LINK if os.path.islink(dest) or (os.path.lexists(dest) and not dest.is_file()) else None


def _backup(dest: Path, target: Path, rel: str, root: Path) -> None:
    keep = root / hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:8] / rel
    keep.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dest, keep)


def _write(dest: Path, data: bytes, mode: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.gsync-{secrets.token_hex(4)}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune_backups(root: Path) -> None:
    try:
        runs = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())
        for old in runs[:-KEEP_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def apply_bundle(bundle: Path, *, home: Path, accounts_root: Path, accounts: Sequence[Any], state: State, backups: Path,
                 stage_root: Path, harnesses: Iterable[str] = rules.HARNESSES) -> Report:
    report = Report()
    wanted = set(harnesses) | {"agents"} if "codex" in set(harnesses) else set(harnesses)
    stage = stage_root / f"global-stage-{secrets.token_hex(6)}"
    stage.mkdir(parents=True, mode=0o700)
    run = backups / time.strftime("%Y%m%dT%H%M%S", time.gmtime()) / secrets.token_hex(2)
    try:
        members = _stage(bundle, stage, wanted)
        by_slot: Dict[str, List[Tuple[str, Path, int]]] = {}
        for slot, rel, path, mode in members:
            by_slot.setdefault(slot, []).append((rel, path, mode))
        written = state.load()
        home_text = str(home)
        for slot, files in sorted(by_slot.items()):
            for target in targets_for(slot, home, accounts_root, accounts):
                if not target.is_dir() and not (slot.endswith(".default") and slot.split(".")[0] in ("claude", "agents")):
                    report.refused.append([f"{slot}", "folder not on this computer"])
                    continue
                report.folders += 1
                done = _apply_target(slot, target, files, home_text, run, report, written.get(str(target), []))
                written[str(target)] = done
                report.targets.append((target, done))
        report.backup = str(run) if run.exists() else None
        state.save(written)
        _prune_backups(backups)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return report


def _apply_target(slot: str, target: Path, files: Sequence[Tuple[str, Path, int]], home: str, run: Path, report: Report,
                  previous: Sequence[str]) -> List[str]:
    checked: Set[str] = set()
    owned: List[str] = []
    new_rels = {rel for rel, _p, _m in files}
    for rel, path, mode in files:
        dest = target / rel
        why = _clear_path(target, rel, checked)
        if why:
            report.refused.append([f"{slot}/{rel}", why])
            continue
        data = scrub.localise_home(path.read_bytes(), home)
        try:
            if os.path.lexists(dest):
                old = dest.read_bytes()
                if rel == "settings.json":
                    data = _merged_settings(data, old)
                if old == data:
                    report.unchanged += 1
                    owned.append(rel)
                    continue
                _backup(dest, target, rel, run)
            _write(dest, data, mode)
        except OSError as exc:
            logger.warning("pack_global_write_failed", slot=slot, errno=exc.errno)
            report.refused.append([f"{slot}/{rel}", f"could not write ({exc.errno})"])
            continue
        report.written += 1
        owned.append(rel)
    for rel in previous:
        if rel in new_rels or rules.path_problem(slot.split(".")[0], rel):
            continue
        dest = target / rel
        if _clear_path(target, rel, set()) is None and dest.is_file():
            try:
                _backup(dest, target, rel, run)
                os.unlink(dest)
                report.removed += 1
                _prune_empty(dest.parent, target)
            except OSError as exc:
                logger.warning("pack_global_remove_failed", slot=slot, errno=exc.errno)
                owned.append(rel)
    return owned


def _merged_settings(received: bytes, existing: bytes) -> bytes:
    try:
        sent = json.loads(received)
        merged = scrub.merge_keep_local(sent, json.loads(existing))
    except ValueError:
        return received
    if merged == sent:
        return received
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _prune_empty(folder: Path, stop: Path) -> None:
    while folder != stop and str(folder).startswith(str(stop)):
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent
