"""Is a task's output file held open by a live child of this claude?

A MONITOR CANNOT BE MEASURED THIS WAY, AND THE CALLER KNOWS IT. The same
measurement found a Monitor's command running with its stdout and stderr
on PIPES to claude, and its output file did not exist until claude wrote
the summary at the end. So this module is only ever asked about shells.

WHY DESCENDANTS AND NOT ANY PROCESS. A shell that re-parented itself to
launchd (``nohup cmd &``) is not this session's work any more, and the
root (claude itself, hundreds of fds) is excluded: claude opens the file
to write a summary, which is not the task running.

THREE ANSWERS, NEVER TWO. ``held``, ``not_held``, and ``unmeasured`` for
anything we could not look at: a platform with neither libproc nor
``/proc``, a descendant whose descriptors the kernel refused, a process
table we do not have, a probe past its budget or unable to get a slot. An
unmeasured task is never read as running and never as finished.

MATCHED BY (device, inode), NOT BY PATH. ``/tmp`` is a symlink to
``/private/tmp`` on macOS and the kernel reports the resolved path, so a
string compare is a trap; the identity of the open vnode is not.

BOUNDED. At most :data:`MAX_CONCURRENT_PROBES` run at once across all
sessions, a probe waits at most :data:`SLOT_WAIT_SECONDS` for a slot and
gives up after :data:`PROBE_BUDGET_SECONDS`, and it looks at no more than
:data:`MAX_PROBED_PROCESSES` descendants. Each look is one ``proc_pidinfo``
call per process plus one ``proc_pidfdinfo`` per vnode descriptor, so a
shell costs a handful of syscalls and no subprocess.
"""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import threading
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)

HELD: str = "held"
NOT_HELD: str = "not_held"
UNMEASURED: str = "unmeasured"

MAX_CONCURRENT_PROBES: int = 2
SLOT_WAIT_SECONDS: float = 0.25
PROBE_BUDGET_SECONDS: float = 0.5
MAX_PROBED_PROCESSES: int = 512

_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_PROBES)

_PROC_PIDLISTFDS = 1
_PROC_PIDFDVNODEINFO = 1
_PROX_FDTYPE_VNODE = 1
_PROC_PIDFDVNODEPATHINFO = 2


class _ProcFdInfo(ctypes.Structure):

    _fields_ = [("proc_fd", ctypes.c_int32), ("proc_fdtype", ctypes.c_uint32)]


class _ProcFileInfo(ctypes.Structure):

    _fields_ = [
        ("fi_openflags", ctypes.c_uint32),
        ("fi_status", ctypes.c_uint32),
        ("fi_offset", ctypes.c_int64),
        ("fi_type", ctypes.c_int32),
        ("fi_guardflags", ctypes.c_uint32),
    ]


class _VinfoStat(ctypes.Structure):

    _fields_ = [
        ("vst_dev", ctypes.c_uint32),
        ("vst_mode", ctypes.c_uint16),
        ("vst_nlink", ctypes.c_uint16),
        ("vst_ino", ctypes.c_uint64),
        ("vst_uid", ctypes.c_uint32),
        ("vst_gid", ctypes.c_uint32),
        ("vst_times", ctypes.c_int64 * 8),
        ("vst_size", ctypes.c_int64),
        ("vst_blocks", ctypes.c_int64),
        ("vst_blksize", ctypes.c_int32),
        ("vst_flags", ctypes.c_uint32),
        ("vst_gen", ctypes.c_uint32),
        ("vst_rdev", ctypes.c_uint32),
        ("vst_qspare", ctypes.c_int64 * 2),
    ]


class _VnodeInfo(ctypes.Structure):

    _fields_ = [
        ("vi_stat", _VinfoStat),
        ("vi_type", ctypes.c_int),
        ("vi_pad", ctypes.c_int),
        ("vi_fsid", ctypes.c_int32 * 2),
    ]


class _VnodeFdInfo(ctypes.Structure):

    _fields_ = [("pfi", _ProcFileInfo), ("pvi", _VnodeInfo)]


class _VnodeInfoPath(ctypes.Structure):

    _fields_ = [("vip_vi", _VnodeInfo), ("vip_path", ctypes.c_char * 1024)]


class _VnodeFdInfoWithPath(ctypes.Structure):

    _fields_ = [("pfi", _ProcFileInfo), ("pvip", _VnodeInfoPath)]


def _load_libproc() -> Optional[ctypes.CDLL]:
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
        ]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_pidfdinfo.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
        ]
        lib.proc_pidfdinfo.restype = ctypes.c_int
        return lib
    except (OSError, AttributeError) as exc:
        logger.warning("output_holders_libproc_unavailable", error=str(exc))
        return None


_LIBPROC = _load_libproc()


class _Unmeasurable(Exception):
    """One process's descriptors could not be read (not: it exited)."""


def _vnodes_libproc(pid: int) -> Optional[Set[Tuple[int, int]]]:
    lib = _LIBPROC
    need = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, None, 0)
    if need <= 0:
        err = ctypes.get_errno()
        if err == errno.ESRCH:
            return None
        raise _Unmeasurable("proc_pidinfo sizing failed, errno %d" % err)
    count = need // ctypes.sizeof(_ProcFdInfo) + 16
    fds = (_ProcFdInfo * count)()
    got = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, fds, ctypes.sizeof(fds))
    if got <= 0:
        err = ctypes.get_errno()
        if err == errno.ESRCH:
            return None
        raise _Unmeasurable("proc_pidinfo listfds failed, errno %d" % err)
    held: Set[Tuple[int, int]] = set()
    info = _VnodeFdInfo()
    for entry in fds[: got // ctypes.sizeof(_ProcFdInfo)]:
        if entry.proc_fdtype != _PROX_FDTYPE_VNODE:
            continue
        size = lib.proc_pidfdinfo(
            pid, entry.proc_fd, _PROC_PIDFDVNODEINFO, ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if size < ctypes.sizeof(info):
            continue
        held.add((int(info.pvi.vi_stat.vst_dev), int(info.pvi.vi_stat.vst_ino)))
    return held


def _vnodes_procfs(pid: int) -> Optional[Set[Tuple[int, int]]]:
    """(dev, ino) of every file ``pid`` holds open, via ``/proc``.

    Output: set, or None when the process no longer exists.
    Raises: _Unmeasurable - its fd directory could not be listed.
    """
    base = "/proc/%d/fd" % pid
    try:
        names = os.listdir(base)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _Unmeasurable(str(exc)) from exc
    held: Set[Tuple[int, int]] = set()
    for name in names:
        try:
            stat = os.stat(os.path.join(base, name))
        except OSError:
            continue
        held.add((stat.st_dev, stat.st_ino))
    return held


def _reader():
    if _LIBPROC is not None:
        return _vnodes_libproc
    if os.path.isdir("/proc/self/fd"):
        return _vnodes_procfs
    return None


def open_file_path(pid: int, fd: int) -> Optional[str]:
    if _LIBPROC is not None:
        info = _VnodeFdInfoWithPath()
        size = _LIBPROC.proc_pidfdinfo(
            pid, fd, _PROC_PIDFDVNODEPATHINFO, ctypes.byref(info), ctypes.sizeof(info),
        )
        if size < ctypes.sizeof(info):
            return None
        raw = info.pvip.vip_path.decode("utf-8", errors="replace")
        return raw or None
    try:
        return os.readlink("/proc/%d/fd/%d" % (pid, fd))
    except OSError:
        return None


def descendants(root_pid: int, process_parents: Mapping[int, int]) -> List[int]:
    children: Dict[int, List[int]] = {}
    for pid, ppid in process_parents.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    found: List[int] = []
    queue = list(children.get(root_pid, ()))
    seen = {root_pid}
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        found.append(pid)
        queue.extend(children.get(pid, ()))
    return found


def _dev_key(dev: int) -> int:
    return dev & 0xFFFFFFFF if _LIBPROC is not None else dev


def _identities(paths: Iterable[str]) -> Tuple[Dict[str, Tuple[int, int]], Dict[str, str]]:
    wanted: Dict[str, Tuple[int, int]] = {}
    answers: Dict[str, str] = {}
    for path in paths:
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            answers[path] = NOT_HELD
            continue
        except OSError:
            answers[path] = UNMEASURED
            continue
        wanted[path] = (_dev_key(stat.st_dev), stat.st_ino)
    return wanted, answers


def probe_output_holders(
    paths: Sequence[str],
    *,
    root_pid: Optional[int],
    process_parents: Optional[Mapping[int, int]],
    budget_seconds: float = PROBE_BUDGET_SECONDS,
) -> Dict[str, str]:
    paths = list(dict.fromkeys(paths))
    read = _reader()
    if not paths:
        return {}
    if read is None or root_pid is None or not process_parents:
        return {path: UNMEASURED for path in paths}
    wanted, answers = _identities(paths)
    if not wanted:
        return answers
    if not _SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        answers.update({path: UNMEASURED for path in wanted})
        return answers
    try:
        return _scan(read, root_pid, process_parents, wanted, answers, budget_seconds)
    finally:
        _SLOTS.release()


def _scan(read, root_pid, process_parents, wanted, answers, budget_seconds) -> Dict[str, str]:
    started = time.monotonic()
    pids = descendants(root_pid, process_parents)
    refused = len(pids) > MAX_PROBED_PROCESSES
    by_identity: Dict[Tuple[int, int], List[str]] = {}
    for path, identity in wanted.items():
        by_identity.setdefault(identity, []).append(path)
    for pid in pids[:MAX_PROBED_PROCESSES]:
        if not by_identity:
            break
        if time.monotonic() - started > budget_seconds:
            refused = True
            break
        try:
            held = read(pid)
        except _Unmeasurable as exc:
            logger.debug("output_holders_process_unreadable", pid=pid, error=str(exc))
            refused = True
            continue
        for identity in list(by_identity):
            if held and identity in held:
                for path in by_identity.pop(identity):
                    answers[path] = HELD
    rest = NOT_HELD if not refused else UNMEASURED
    for paths_left in by_identity.values():
        for path in paths_left:
            answers[path] = rest
    return answers


__all__ = [
    "HELD", "NOT_HELD", "UNMEASURED", "descendants", "open_file_path", "probe_output_holders",
    "MAX_CONCURRENT_PROBES", "PROBE_BUDGET_SECONDS", "MAX_PROBED_PROCESSES",
]
