
from __future__ import annotations

import os
import re
import sys
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

COUNTED_EVENTS = ("subprocess.Popen", "os.scandir", "os.listdir", "open", "sqlite3.connect")
TOP_ROWS = 25
ARGV_WORDS = 5
CALLER_DEPTH = 4

_THREAD_SUFFIX = re.compile(r"(_|-)\d+$")

_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + os.sep
_SELF_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep
_REPO_ROOT = os.path.dirname(_SRC_ROOT.rstrip(os.sep)) + os.sep
_STDLIB = os.path.dirname(os.__file__) + os.sep

_lock = threading.Lock()
_installed = False
_active = False
_counts: Counter = Counter()


def _detail(event: str, args: Tuple[Any, ...]) -> str:
    if event == "subprocess.Popen":
        argv = args[1] if len(args) > 1 else None
        if isinstance(argv, (list, tuple)) and argv:
            words = [os.path.basename(os.fsdecode(argv[0]))]
            for word in argv[1:ARGV_WORDS]:
                text = os.fsdecode(word) if isinstance(word, (str, bytes)) else str(word)
                words.append("*" if len(text) > 24 or "=" in text or "/" in text else text)
            return " ".join(words)
        return os.path.basename(str(args[0])) if args else "?"
    target = args[0] if args else None
    if isinstance(target, int) or target is None:
        return "<fd>" if isinstance(target, int) else "."
    path = os.fsdecode(target) if isinstance(target, (str, bytes, os.PathLike)) else str(target)
    if event == "open":
        path = os.path.dirname(path)
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    return path[-120:]


def _caller() -> str:
    frame = sys._getframe(2)
    leaf = outside_stdlib = None
    ours: List[str] = []
    while frame is not None and len(ours) < CALLER_DEPTH:
        name = frame.f_code.co_filename
        leaf = leaf or frame
        if name.startswith(_SRC_ROOT) and not name.startswith(_SELF_DIR):
            ours.append(f"{name[len(_REPO_ROOT):]}:{frame.f_code.co_name}:{frame.f_lineno}")
        elif outside_stdlib is None and not name.startswith(_STDLIB) and not name.startswith("<frozen"):
            outside_stdlib = frame
        frame = frame.f_back
    if ours:
        return " < ".join(ours)
    pick = outside_stdlib or leaf
    if pick is None:
        return "?"
    return f"{os.path.basename(pick.f_code.co_filename)}:{pick.f_code.co_name}:{pick.f_lineno}"


def thread_group(name: str) -> str:
    return _THREAD_SUFFIX.sub(lambda m: m.group(1) + "*", name)


def _hook(event: str, args: Tuple[Any, ...]) -> None:
    if not _active or event not in COUNTED_EVENTS:
        return
    key = (event, _detail(event, args), _caller(), thread_group(threading.current_thread().name))
    with _lock:
        _counts[key] += 1


def start() -> None:
    global _installed, _active
    with _lock:
        if _active:
            raise RuntimeError("a call count window is already open")
        _counts.clear()
        if not _installed:
            sys.addaudithook(_hook)
            _installed = True
        _active = True


def stop(seconds: float) -> Dict[str, List[Dict[str, Any]]]:
    global _active
    with _lock:
        _active = False
        rows = list(_counts.items())
        _counts.clear()
    out: Dict[str, List[Dict[str, Any]]] = {event: [] for event in COUNTED_EVENTS}
    for (event, detail, caller, thread), count in sorted(rows, key=lambda r: -r[1]):
        if len(out[event]) < TOP_ROWS:
            out[event].append({
                "detail": detail, "caller": caller, "thread": thread, "count": count,
                "per_second": round(count / seconds, 3) if seconds > 0 else None,
            })
    out["totals"] = [
        {"event": event, "count": sum(c for (e, *_), c in rows if e == event)} for event in COUNTED_EVENTS
    ]
    return out


def is_active() -> bool:
    return _active


def installed() -> Optional[bool]:
    return _installed
