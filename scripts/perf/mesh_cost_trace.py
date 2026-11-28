
from __future__ import annotations

import ctypes
import gc
import os
import re
import subprocess
import sys
import threading
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
_UNITS = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "B": 1}


def _not(reason: object) -> str:
    return f"not measured: {type(reason).__name__ if isinstance(reason, BaseException) else reason}"


def _bytes(text: str) -> int:
    m = re.fullmatch(r"([0-9.]+)([KMGB]?)", text)
    return int(float(m.group(1)) * _UNITS[m.group(2) or "B"]) if m else 0


def _type_name(t: type) -> str:
    mod, qual = getattr(t, "__module__", None), getattr(t, "__qualname__", None)
    return f"{mod if isinstance(mod, str) else '?'}.{qual if isinstance(qual, str) else '?'}"


def _type_counts(objs: List[Any], limit: int = 40) -> List[List[Any]]:
    return [[name, n] for name, n in Counter(_type_name(type(o)) for o in objs).most_common(limit)]


def _sqlite_memory() -> Dict[str, Any]:
    try:
        import _sqlite3

        lib = ctypes.CDLL(_sqlite3.__file__)
        for name in ("sqlite3_memory_used", "sqlite3_memory_highwater"):
            getattr(lib, name).restype = ctypes.c_int64
        lib.sqlite3_memory_highwater.argtypes = [ctypes.c_int]
        return {"memory_used": int(lib.sqlite3_memory_used()), "memory_highwater": int(lib.sqlite3_memory_highwater(0))}
    except (ImportError, OSError, AttributeError) as exc:
        return {"memory_used": _not(exc), "memory_highwater": _not(exc)}


def _mstats() -> Any:
    class MStats(ctypes.Structure):
        _fields_ = [("bytes_total", ctypes.c_size_t), ("chunks_used", ctypes.c_size_t), ("bytes_used", ctypes.c_size_t),
                    ("chunks_free", ctypes.c_size_t), ("bytes_free", ctypes.c_size_t)]

    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.mstats.restype = MStats
        st = libc.mstats()
        return {"bytes_total": st.bytes_total, "bytes_used": st.bytes_used, "bytes_free": st.bytes_free}
    except (OSError, AttributeError) as exc:
        return _not(exc)


def _pymalloc(root: Path) -> Any:
    path = root / "pymalloc.txt"
    try:
        sys.stderr.flush()
        saved = os.dup(2)
        with open(path, "w") as sink:
            os.dup2(sink.fileno(), 2)
            try:
                sys._debugmallocstats()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
        out: Dict[str, int] = {}
        for line in path.read_text().splitlines():
            m = re.match(r"\s*(.+?)\s+=\s+([\d,]+)\s*$", line)
            if m and (m.group(1).startswith(("# bytes", "# arenas", "Total")) or "unused pools" in m.group(1) or "bytes/arena" in m.group(1)):
                out.setdefault(m.group(1).strip("# ").strip(), int(m.group(2).replace(",", "")))
        return out or _not("no totals parsed")
    except OSError as exc:
        return _not(exc)


def _vmmap(pid: int, root: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        summary = subprocess.run(["vmmap", "-summary", str(pid)], capture_output=True, text=True, timeout=90).stdout
        full = subprocess.run(["vmmap", str(pid)], capture_output=True, text=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return {"summary": _not(exc), "db_regions": _not(exc)}
    keep = ("MALLOC", "mapped file", "TOTAL", "Physical footprint", "DefaultMallocZone", "QuantumMallocZone", "ProtectedMallocZone", "Python")
    out["summary"] = [ln.rstrip() for ln in summary.splitlines() if ln.startswith(keep)][:40] or _not("vmmap printed nothing parseable")
    regions, resident, virtual = 0, 0, 0
    for ln in full.splitlines():
        if "carnivore.db" in ln:
            m = re.search(r"\[\s*(\S+)\s+(\S+)\s+\S+\s+\S+\]", ln)
            if m:
                regions += 1
                virtual += _bytes(m.group(1))
                resident += _bytes(m.group(2))
    out["db_regions"] = {"count": regions, "virtual_bytes": virtual, "resident_bytes": resident,
                         "caveat": "the same file mapped by several connections may be counted once per mapping or once in all"}
    return out


def _rss(pid: int) -> Any:
    try:
        return int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()) * 1024
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return _not(exc)


def _db_files() -> Dict[str, Any]:
    base = os.environ.get("CARNIVORE_STATE_DIR")
    if not base:
        return _not("no CARNIVORE_STATE_DIR")
    return {name: (os.path.getsize(Path(base) / name) if (Path(base) / name).exists() else None) for name in ("carnivore.db", "carnivore.db-wal")}


def mark(root: Path) -> Dict[str, Any]:
    gc.collect()
    pid = os.getpid()
    tracing = tracemalloc.is_tracing()
    gen2 = gc.get_objects(generation=2)
    everything = gc.get_objects()
    rec: Dict[str, Any] = {
        "rss_bytes": _rss(pid),
        "tracemalloc": {"current": tracemalloc.get_traced_memory()[0], "peak": tracemalloc.get_traced_memory()[1], "overhead": tracemalloc.get_tracemalloc_memory()} if tracing else _not("tracing off"),
        "gc": {"counts": [len(gc.get_objects(generation=g)) for g in (0, 1, 2)], "frozen": gc.get_freeze_count(), "thresholds": list(gc.get_threshold()),
               "stats": gc.get_stats()},
        "types_all": _type_counts(everything), "types_gen2": _type_counts(gen2), "tracked_total": len(everything),
        "sqlite_connections": sum(1 for o in everything if _type_name(type(o)) == "sqlite3.Connection"),
        "threads": threading.active_count(), "sqlite": _sqlite_memory(), "db_files": _db_files(), "mstats": _mstats(), "pymalloc": _pymalloc(root),
        "vmmap": _vmmap(pid, root),
    }
    del everything, gen2
    return rec


def snapshot() -> "tracemalloc.Snapshot":
    return tracemalloc.take_snapshot().filter_traces([tracemalloc.Filter(False, tracemalloc.__file__), tracemalloc.Filter(False, __file__)])


def _where(filename: str) -> str:
    if filename.startswith(str(REPO)):
        return os.path.relpath(filename, REPO)
    return "site-packages/" + filename.split("site-packages/", 1)[1] if "site-packages/" in filename else os.path.basename(filename)


def diff(a: "tracemalloc.Snapshot", b: "tracemalloc.Snapshot", limit: int = 25) -> Dict[str, Any]:
    sites = []
    for st in b.compare_to(a, "traceback")[:limit]:
        sites.append({"size_diff": st.size_diff, "count_diff": st.count_diff, "size": st.size, "count": st.count,
                      "frames": [f"{_where(f.filename)}:{f.lineno}" for f in reversed(st.traceback)]})
    files = [{"file": _where(st.traceback[0].filename), "size_diff": st.size_diff, "count_diff": st.count_diff}
             for st in b.compare_to(a, "filename")[:limit]]
    return {"by_traceback": sites, "by_filename": files}


def start() -> None:
    tracemalloc.start(25)
    tracemalloc.reset_peak()


def holders(type_name: str, known: "set[int]", samples: int = 3, depth: int = 4) -> Dict[str, Any]:
    live = [o for o in gc.get_objects() if _type_name(type(o)) == type_name]
    unknown = [o for o in live if id(o) not in known]
    chains: List[List[str]] = []
    skip = {id(live), id(unknown)}
    for obj in unknown[:samples]:
        level, path = [obj], []
        for _ in range(depth):
            refs = [r for r in gc.get_referrers(*level) if id(r) not in skip and type(r).__name__ != "frame" and r is not level]
            if not refs:
                break
            path.append(sorted({_type_name(type(r)) + (f"[{len(r)}]" if isinstance(r, (list, tuple, set, dict)) else "") for r in refs})[:4])
            level = refs[:6]
        chains.append(path)
    return {"live": len(live), "known": len(live) - len(unknown), "unknown": len(unknown), "chains": chains}
