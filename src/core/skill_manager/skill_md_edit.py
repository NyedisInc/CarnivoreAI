
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from src.core.pack.skills.secrets_gate import content_problem
from src.core.skill_manager.local_skill_md import resolve_skill_md
from src.core.skill_manager.scan import MAX_SKILL_MD_BYTES
from src.core.skill_manager.skill_md_versions import SkillMdVersionStore
from src.core.skill_manager.types import OverrideError, SCOPE_PLUGIN, SCOPE_SYSTEM
from src.core.test_write_guard import assert_test_write_allowed

MAX_EDIT_BYTES = MAX_SKILL_MD_BYTES
_LOCK = threading.Lock()


class StaleBase(OverrideError):

    def __init__(self, current_sha256: str) -> None:
        super().__init__(409, "stale", "SKILL.md changed since you opened it")
        self.current_sha256 = current_sha256


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_path(location: Dict[str, Any], root: Dict[str, Any], *, write: bool) -> str:
    if write and (root.get("read_only") or root.get("scope") in (SCOPE_PLUGIN, SCOPE_SYSTEM)):
        raise OverrideError(403, "read_only", "plugin and Codex system skills are read only")
    return resolve_skill_md(location, root)[0]


def _replace_file(path: str, data: bytes) -> None:
    assert_test_write_allowed(Path(path))
    mode = stat.S_IMODE(os.stat(path).st_mode)
    fd, tmp = tempfile.mkstemp(prefix=".skill-md-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def _swap(store: SkillMdVersionStore, path: str, data: bytes, base_sha256: str, note: str, action: str) -> Tuple[str, int]:
    try:
        with _LOCK:
            if os.path.getsize(path) > MAX_EDIT_BYTES:
                raise OverrideError(409, "too_large_to_edit", "SKILL.md is too large to edit here")
            with open(path, "rb") as handle:
                current = handle.read()
            current_sha = hashlib.sha256(current).hexdigest()
            if current_sha != base_sha256:
                raise StaleBase(current_sha)
            now = time.time()
            if store.latest_sha(path) != current_sha:
                leaked = content_problem("SKILL.md", current) is not None
                store.add(path, now, "", "baseline", current_sha, current, redacted=leaked)
            _replace_file(path, data)
            new_sha = hashlib.sha256(data).hexdigest()
            version_id = store.add(path, now, note, action, new_sha, data)
    except FileNotFoundError:
        raise OverrideError(404, "gone", "that SKILL.md is no longer there")
    return new_sha, version_id


def save_edit(
    store: SkillMdVersionStore, location: Dict[str, Any], root: Dict[str, Any], content: str, base_sha256: str, note: str = ""
) -> Tuple[str, int]:
    path = target_path(location, root, write=True)
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        raise OverrideError(422, "not_utf8", "SKILL.md must be valid UTF-8 text")
    if len(data) > MAX_EDIT_BYTES:
        raise OverrideError(413, "too_large", f"SKILL.md is capped at {MAX_EDIT_BYTES} bytes")
    if content_problem("SKILL.md", data) is not None:
        raise OverrideError(422, "secret_detected", "the text looks like it holds a credential; remove it and save again")
    return _swap(store, path, data, base_sha256, note, "edit")


def restore_version(
    store: SkillMdVersionStore, location: Dict[str, Any], root: Dict[str, Any], version_id: int, base_sha256: str
) -> Tuple[str, int]:
    path = target_path(location, root, write=True)
    found = store.get(path, version_id)
    if found is None:
        raise OverrideError(404, "unknown_version", "no such saved version of this file")
    if found[2]:
        raise OverrideError(409, "version_redacted", "that version held a credential, so its text was not kept")
    return _swap(store, path, found[0], base_sha256, f"restored version {version_id}", "restore")
