
from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.pack.globalsync import rules, scrub
from src.core.pack.skills import secrets_gate

logger = structlog.get_logger()


@dataclass(frozen=True)
class Slot:

    id: str
    kind: str
    root: Path


@dataclass
class Built:

    path: Path
    digest: str = ""
    files: int = 0
    size: int = 0
    slots: Dict[str, int] = field(default_factory=dict)
    refused: List[List[str]] = field(default_factory=list)
    scrubbed: int = 0

    def summary(self) -> Dict[str, Any]:
        return {"files": self.files, "bytes": self.size, "slots": dict(self.slots), "scrubbed": self.scrubbed,
                "refused": self.refused[:rules.MAX_REFUSALS_KEPT], "refused_total": len(self.refused)}


def slots_for(home: Path, accounts: Iterable[Any], harnesses: Iterable[str]) -> List[Slot]:
    chosen = set(harnesses)
    out: List[Slot] = []
    seen: Set[str] = set()

    def add(slot_id: str, kind: str, root: Path) -> None:
        real = os.path.realpath(root)
        if rules.SLOT_RE.match(slot_id) and root.is_dir() and real not in seen:
            seen.add(real)
            out.append(Slot(slot_id, kind, root))

    if "claude" in chosen:
        add("claude.default", "claude", home / ".claude")
    if "codex" in chosen:
        add("codex.default", "codex", home / ".codex")
        add("agents.default", "agents", home / ".agents")
    for account in accounts:
        if account.provider == "claude" and "claude" in chosen and account.claude_config_dir:
            add(f"claude.{account.id}", "claude", Path(os.path.expanduser(account.claude_config_dir)))
        elif account.provider == "codex" and "codex" in chosen and account.codex_home:
            add(f"codex.{account.id}", "codex", Path(os.path.expanduser(account.codex_home)))
    return out


def _entries(slot: Slot) -> Iterator[Tuple[str, Path]]:
    try:
        names = sorted(os.listdir(slot.root))
    except OSError as exc:
        logger.info("pack_global_slot_unreadable", slot=slot.id, errno=exc.errno)
        return
    for name in names:
        if rules.is_denied(name) or rules.is_litter(name) or rules.is_machine_local(name) or (slot.kind == "agents" and name != "skills"):
            continue
        if name == "plugins" and slot.kind == "claude":
            for rel in (*rules.PLUGIN_FILES, *rules.PLUGIN_DIRS):
                sub = slot.root / rel
                if os.path.lexists(sub):
                    yield rel, Path(os.path.realpath(sub))
            continue
        real = Path(os.path.realpath(slot.root / name))
        if real.is_dir() or real.is_file():
            yield name, real


def _walk(rel: str, real: Path) -> Iterator[Tuple[str, Path, bool]]:
    if real.is_file():
        yield rel, real, False
        return
    for here, dirs, files in os.walk(real, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not rules.is_machine_local(d))
        base = os.path.relpath(here, real)
        prefix = rel if base == "." else f"{rel}/{base}"
        for d in list(dirs):
            if os.path.islink(os.path.join(here, d)):
                dirs.remove(d)
                yield f"{prefix}/{d}", Path(here) / d, True
        for name in sorted(files):
            if not rules.is_litter(name):
                yield f"{prefix}/{name}", Path(here) / name, os.path.islink(os.path.join(here, name))


def _read(path: Path, rel: str, home: str) -> Tuple[Optional[bytes], Optional[str], int]:
    if secrets_gate.name_problem(rel):
        return None, "credential file", 0
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_size > rules.MAX_FILE_BYTES:
                return None, rules.REASON_TOO_LARGE, 0
            data = handle.read()
    except OSError as exc:
        return None, f"unreadable ({exc.errno})", 0
    dropped = 0
    if os.path.basename(rel) in rules.SCRUBBED_NAMES:
        cleaned, names = scrub.scrub_text(os.path.basename(rel), data)
        if cleaned is None:
            return None, "holds secrets that could not be scrubbed", 0
        data, dropped = cleaned, len(names)
    data = scrub.tokenise_home(data, home)
    if secrets_gate.content_problem(rel, data):
        return None, "credential pattern", 0
    return data, None, dropped


def build(slots: Sequence[Slot], out: Path, home: Path) -> Built:
    built = Built(out)
    digest = hashlib.sha256()
    out.parent.mkdir(parents=True, exist_ok=True)
    seen: Set[str] = set()
    with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as raw, \
            tarfile.open(fileobj=raw, mode="w:gz", compresslevel=3) as tar:
        for slot in slots:
            for top, real in _entries(slot):
                if str(real) in seen:
                    continue
                seen.add(str(real))
                for rel, path, is_link in _walk(top, real):
                    ref = f"{slot.id}/{rel}"
                    if is_link:
                        built.refused.append([ref, rules.REASON_LINK])
                    elif built.files >= rules.MAX_FILES or built.size >= rules.MAX_TOTAL_BYTES:
                        built.refused.append([ref, rules.REASON_BUDGET])
                    elif (problem := rules.path_problem(slot.kind, rel)) is not None:
                        built.refused.append([ref, problem])
                    else:
                        data, reason, dropped = _read(path, rel, str(home))
                        if data is None:
                            built.refused.append([ref, reason or "unreadable"])
                            continue
                        mode = _mode(path)
                        info = tarfile.TarInfo(ref)
                        info.size, info.mode, info.mtime = len(data), mode, int(time.time())
                        tar.addfile(info, io.BytesIO(data))
                        digest.update(f"{ref}\0{mode}\0{hashlib.sha256(data).hexdigest()}\n".encode("utf-8"))
                        built.files += 1
                        built.size += len(data)
                        built.scrubbed += dropped
                        built.slots[slot.id] = built.slots.get(slot.id, 0) + 1
    built.digest = digest.hexdigest()
    return built


def _mode(path: Path) -> int:
    try:
        return ((os.lstat(path).st_mode & 0o777) & ~0o022) | 0o600
    except OSError:
        return 0o644
