
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Dict, NamedTuple, Optional

import structlog

logger = structlog.get_logger()

_THREAD_BASIC_INFO = 3
_THREAD_BASIC_INFO_COUNT = 10
_THREAD_IDENTIFIER_INFO = 4
_THREAD_IDENTIFIER_INFO_COUNT = 6
_KERN_SUCCESS = 0
_TH_STATE_RUNNING = 1
_PORT_BYTES = ctypes.sizeof(ctypes.c_uint32)


class ThreadCpu(NamedTuple):

    seconds: float
    running: bool


class _TimeValue(ctypes.Structure):
    _fields_ = [("seconds", ctypes.c_int32), ("microseconds", ctypes.c_int32)]


class _ThreadBasicInfo(ctypes.Structure):
    _fields_ = [
        ("user_time", _TimeValue),
        ("system_time", _TimeValue),
        ("cpu_usage", ctypes.c_int32),
        ("policy", ctypes.c_int32),
        ("run_state", ctypes.c_int32),
        ("flags", ctypes.c_int32),
        ("suspend_count", ctypes.c_int32),
        ("sleep_time", ctypes.c_int32),
    ]


class _ThreadIdentifierInfo(ctypes.Structure):
    _fields_ = [
        ("thread_id", ctypes.c_uint64),
        ("thread_handle", ctypes.c_uint64),
        ("dispatch_qaddr", ctypes.c_uint64),
    ]


class _Mach:

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise OSError("per-thread CPU is read through Mach, macOS only")
        libc = ctypes.PyDLL(ctypes.util.find_library("c"))
        self.task = ctypes.c_uint32.in_dll(libc, "mach_task_self_").value
        self.task_threads = libc.task_threads
        self.task_threads.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)), ctypes.POINTER(ctypes.c_uint32),
        ]
        self.task_threads.restype = ctypes.c_int
        self.thread_info = libc.thread_info
        self.thread_info.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.thread_info.restype = ctypes.c_int
        self.port_deallocate = libc.mach_port_deallocate
        self.port_deallocate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.port_deallocate.restype = ctypes.c_int
        self.vm_deallocate = libc.vm_deallocate
        self.vm_deallocate.argtypes = [ctypes.c_uint32, ctypes.c_size_t, ctypes.c_size_t]
        self.vm_deallocate.restype = ctypes.c_int

    def thread_cpu(self, port: int) -> Optional[tuple]:
        ident = _ThreadIdentifierInfo()
        count = ctypes.c_uint32(_THREAD_IDENTIFIER_INFO_COUNT)
        if self.thread_info(port, _THREAD_IDENTIFIER_INFO, ctypes.byref(ident), ctypes.byref(count)) != _KERN_SUCCESS:
            return None
        basic = _ThreadBasicInfo()
        count = ctypes.c_uint32(_THREAD_BASIC_INFO_COUNT)
        if self.thread_info(port, _THREAD_BASIC_INFO, ctypes.byref(basic), ctypes.byref(count)) != _KERN_SUCCESS:
            return None
        seconds = (
            basic.user_time.seconds + basic.system_time.seconds
            + (basic.user_time.microseconds + basic.system_time.microseconds) / 1e6
        )
        return int(ident.thread_id), ThreadCpu(seconds, basic.run_state == _TH_STATE_RUNNING)

    def read(self) -> Optional[Dict[int, ThreadCpu]]:
        array = ctypes.POINTER(ctypes.c_uint32)()
        count = ctypes.c_uint32(0)
        if self.task_threads(self.task, ctypes.byref(array), ctypes.byref(count)) != _KERN_SUCCESS:
            return None
        out: Dict[int, ThreadCpu] = {}
        try:
            for i in range(count.value):
                port = array[i]
                try:
                    row = self.thread_cpu(port)
                finally:
                    self.port_deallocate(self.task, port)
                if row is not None:
                    out[row[0]] = row[1]
        finally:
            address = ctypes.cast(array, ctypes.c_void_p).value or 0
            self.vm_deallocate(self.task, address, count.value * _PORT_BYTES)
        return out


_MACH: Optional[_Mach] = None
_UNAVAILABLE = False


def read_thread_cpu() -> Optional[Dict[int, ThreadCpu]]:
    global _MACH, _UNAVAILABLE
    if _UNAVAILABLE:
        return None
    if _MACH is None:
        try:
            _MACH = _Mach()
        except (OSError, AttributeError, ValueError) as exc:
            _UNAVAILABLE = True
            logger.info("thread_cpu_unavailable", reason=str(exc))
            return None
    return _MACH.read()
