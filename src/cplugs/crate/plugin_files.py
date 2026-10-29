
from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.forbidden import DatalessSource, SourceForbidden, open_source
from src.cplugs.crate.plan_files import PlannedFile
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs


@dataclass
class PluginWalk:

    files: List[PlannedFile] = field(default_factory=list)
    blockers: List[Tuple[str, str]] = field(default_factory=list)
    excluded: List[Dict[str, Any]] = field(default_factory=list)


def home_of(plugin_id: str) -> str:
    return f"{P.HOME_PLUGIN_PREFIX}{plugin_id}"


def _plan_file(walk: PluginWalk, art: cs.Artifact, decision: P.Decision, real_root: str, path: str, rel: str,
               deny: Set[Tuple[int, int]]) -> None:
    plugin, data = str(art.locator["plugin"]), str(art.locator["data"])
    crate_rel = f"{data}/{rel}"
    try:
        cf.check_rel(crate_rel)
        cf.check_token(home_of(plugin), "home kind")
        fd, st = open_source(path, [real_root], deny)
    except cf.UnsafeName as exc:
        walk.blockers.append((K.B_FORBIDDEN, f"{path}: not a name a crate can carry ({exc})"))
        return
    except DatalessSource as exc:
        walk.blockers.append((K.B_DATALESS, str(exc)))
        return
    except SourceForbidden as exc:
        walk.blockers.append((K.B_FORBIDDEN, str(exc)))
        return
    except OSError as exc:
        walk.blockers.append((K.B_FORBIDDEN, f"{path} could not be opened ({type(exc).__name__})"))
        return
    os.close(fd)
    walk.files.append(PlannedFile(
        key=decision.key, role=P.R_PLUGIN_FILE, home=home_of(plugin), home_index=0, rel=crate_rel, source_path=path,
        conversation_id=None, family=None, enc_folder=None, line_mode=False, size=st.st_size, ino=st.st_ino,
        mtime_ns=st.st_mtime_ns, mode=st.st_mode & 0o7777, artifact=art.what, plugin=plugin, data=data, plugin_root=real_root))


def _unlistable(walk: PluginWalk, exc: OSError) -> None:
    where = getattr(exc, "filename", None) or "a folder of the store"
    if exc.errno == errno.EDEADLK:
        walk.blockers.append((K.B_DATALESS, f"{where} is only in iCloud, not on this disk"))
    elif not isinstance(exc, FileNotFoundError):
        walk.blockers.append((K.B_FORBIDDEN, f"{where} could not be listed ({type(exc).__name__})"))


def _walk_unit(walk: PluginWalk, art: cs.Artifact, decision: P.Decision, real_root: str, unit: Dict[str, Any],
               deny: Set[Tuple[int, int]]) -> None:
    path = os.path.join(real_root, unit["rel"])
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        walk.blockers.append((K.B_FORBIDDEN, f"{path} could not be read ({type(exc).__name__})"))
        return
    if stat.S_ISLNK(mode):
        walk.excluded.append({"kind": "policy", "store": art.store, "what": path, "reason": "symlink, not followed"})
    elif stat.S_ISREG(mode):
        _plan_file(walk, art, decision, real_root, path, unit["rel"], deny)
    elif stat.S_ISDIR(mode):
        for folder, dirnames, filenames in os.walk(path, followlinks=False, onerror=lambda exc: _unlistable(walk, exc)):
            dirnames.sort()
            links = [d for d in dirnames if os.path.islink(os.path.join(folder, d))]
            dirnames[:] = [d for d in dirnames if d not in links]
            for name in sorted(filenames) + links:
                full = os.path.join(folder, name)
                if os.path.islink(full) or not os.path.isfile(full):
                    walk.excluded.append({"kind": "policy", "store": art.store, "what": full, "reason": "symlink or special file, not carried"})
                    continue
                _plan_file(walk, art, decision, real_root, full, os.path.relpath(full, real_root).replace(os.sep, "/"), deny)


def plan_plugin_store(art: cs.Artifact, decision: P.Decision, deny: Set[Tuple[int, int]]) -> PluginWalk:
    walk = PluginWalk()
    root: Optional[str] = art.locator.get("root")
    if not root:
        return walk
    real_root = os.path.realpath(root)
    for unit in art.locator.get("units") or []:
        _walk_unit(walk, art, decision, real_root, unit, deny)
    walk.files.sort(key=lambda f: f.rel)
    return walk


def store_view(art: cs.Artifact, decision: P.Decision, walk: Optional[PluginWalk]) -> Dict[str, Any]:
    files = walk.files if walk is not None else []
    return {"store": art.store, "plugin": art.locator.get("plugin"), "data": art.locator.get("data"), "decision": decision.action,
            "files": len(files), "bytes": sum(f.size for f in files), "out_of_scope": int(art.locator.get("out_of_scope") or 0),
            "reason": decision.reason}
