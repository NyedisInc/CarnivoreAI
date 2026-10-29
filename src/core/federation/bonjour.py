"""A ctypes wrapper over macOS's own ``dns_sd`` C API. No new dependency.

WHY CTYPES AND NOT A PYPI PACKAGE. ``dns_sd.h`` is part of libSystem, the
C library every macOS process already links, so the whole Bonjour client
is reachable with no extra wheel, no extra supply-chain surface, and no
version to pin. The API is C-stable (it has not broken source
compatibility since Mac OS X 10.4) so binding it by hand is a one-time
cost, not an ongoing one.

THE FIVE CALLS THIS FILE WRAPS, and nothing else:
``DNSServiceRegister`` (advertise), ``DNSServiceBrowse`` (watch for
instances), ``DNSServiceResolve`` (an instance name to a host and port),
``DNSServiceGetAddrInfo`` (a host name to IPv4/IPv6 addresses), and the
three that drive the event loop: ``DNSServiceRefSockFD``,
``DNSServiceProcessResult``, ``DNSServiceRefDeallocate``.

THE EVENT-LOOP CONTRACT (load bearing, read before calling anything
here). Every one of the four "start" calls above hands back a
``DNSServiceRef``, an opaque connection to the ``mDNSResponder`` daemon.
``DNSServiceRefSockFD`` returns the Unix domain socket backing that
connection. The caller is responsible for watching that fd for
readability and, ONLY when it is readable, calling
``DNSServiceProcessResult`` - which reads exactly the reply already
waiting and invokes the Python callback synchronously, on the calling
stack. This module never blocks on the socket itself: ``process_result``
is safe to call from ``asyncio``'s ``add_reader`` callback because the
data is already buffered by the time the loop says the fd is readable.
Calling it with nothing waiting WOULD block, which is the one thing
callers must never do. Driving the fd is ``discovery.py``'s job, not
this module's; this module owns the C boundary only.

CALLBACK LIFETIME. A ``ctypes.CFUNCTYPE`` instance is a normal Python
object: nothing pins it once its last reference is dropped, even though
the C side still holds a *bare function pointer* into it. If it is
garbage collected while ``mDNSResponder`` still expects to call it, the
process crashes on the next reply. Every constructor below hangs its
callback trampoline off the returned :class:`ServiceRef` for exactly
this reason, and a caller that drops the ``ServiceRef`` before calling
``deallocate()`` has the same bug the C side would have from a dangling
pointer.

TXT RECORDS ARE BUILT AND PARSED AS RAW BYTES, NOT VIA
``TXTRecordCreate``/``TXTRecordSetValue``. The wire format is
public and trivial - a sequence of ``<1-byte length><key>=<value>``
entries, no key or value ever containing an embedded ``=`` beyond the
first, and no entry over 255 bytes - so binding four more C functions to
build what is, in the end, four lines of Python would only add ctypes
surface without buying anything. :func:`encode_txt` and
:func:`decode_txt` are pure functions in this module for that reason and
are unit-testable with no library loaded at all.

PORT BYTE ORDER. ``DNSServiceRegister``'s ``port`` argument and
``DNSServiceResolveReply``'s ``port`` field are both **network byte
order** (big-endian), per ``dns_sd.h``. Every function here takes and
returns a plain host-order Python ``int``; the network-order conversion
happens at the ctypes boundary in this module only, via
``socket.htons``/``socket.ntohs``, so nothing above this file ever has
to think about it.

TESTABILITY. Nothing in this module touches ``mDNSResponder`` at import
time. The C library is loaded lazily, once, through :func:`get_library`,
which accepts an injectable loader so a test can hand it a fake object
exposing the same five function names with the same call signature (a
"shim") with no need for macOS or a running ``mDNSResponder`` at all.
:func:`reset_library` clears the cache between tests.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import socket
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

__all__ = [
    "BonjourUnavailableError",
    "DNSServiceError",
    "ServiceRef",
    "DiscoveredAddress",
    "kDNSServiceInterfaceIndexAny",
    "kDNSServiceFlagsAdd",
    "kDNSServiceFlagsMoreComing",
    "kDNSServiceProtocol_IPv4",
    "kDNSServiceProtocol_IPv6",
    "encode_txt",
    "decode_txt",
    "get_library",
    "reset_library",
    "register",
    "browse",
    "resolve",
    "get_addr_info",
]


kDNSServiceInterfaceIndexAny = 0
kDNSServiceFlagsAdd = 0x2
kDNSServiceFlagsMoreComing = 0x1
kDNSServiceProtocol_IPv4 = 0x01
kDNSServiceProtocol_IPv6 = 0x02
_kDNSServiceErr_NoError = 0

_DNSServiceFlags_t = ctypes.c_uint32
_DNSServiceErrorType_t = ctypes.c_int32
_DNSServiceRef_t = ctypes.c_void_p

_RegisterReply_t = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    _DNSServiceFlags_t,
    _DNSServiceErrorType_t,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)

_BrowseReply_t = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    _DNSServiceFlags_t,
    ctypes.c_uint32,
    _DNSServiceErrorType_t,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)

_ResolveReply_t = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    _DNSServiceFlags_t,
    ctypes.c_uint32,
    _DNSServiceErrorType_t,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_uint16,
    ctypes.c_uint16,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_void_p,
)

_GetAddrInfoReply_t = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    _DNSServiceFlags_t,
    ctypes.c_uint32,
    _DNSServiceErrorType_t,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_void_p,
)


class _sockaddr_in(ctypes.Structure):

    _fields_ = [
        ("sin_len", ctypes.c_uint8),
        ("sin_family", ctypes.c_uint8),
        ("sin_port", ctypes.c_uint16),
        ("sin_addr", ctypes.c_ubyte * 4),
        ("sin_zero", ctypes.c_ubyte * 8),
    ]


class _sockaddr_in6(ctypes.Structure):

    _fields_ = [
        ("sin6_len", ctypes.c_uint8),
        ("sin6_family", ctypes.c_uint8),
        ("sin6_port", ctypes.c_uint16),
        ("sin6_flowinfo", ctypes.c_uint32),
        ("sin6_addr", ctypes.c_ubyte * 16),
        ("sin6_scope_id", ctypes.c_uint32),
    ]


class BonjourUnavailableError(RuntimeError):
    """``dns_sd`` could not be loaded (not macOS, or libSystem missing
    the symbol). Raised at first real use, never at import time."""


class DNSServiceError(RuntimeError):

    def __init__(self, code: int, where: str) -> None:
        self.code = code
        super().__init__(f"dns_sd error {code} in {where}")


@dataclass(frozen=True)
class DiscoveredAddress:

    address: str
    family: int



_lib_cache: Optional[ctypes.CDLL] = None


def get_library(loader: Optional[Callable[[], object]] = None):
    global _lib_cache
    if _lib_cache is not None:
        return _lib_cache

    if loader is not None:
        _lib_cache = loader()
        return _lib_cache

    if sys.platform != "darwin":
        raise BonjourUnavailableError(
            "dns_sd is a macOS-only API; this process is not on darwin"
        )

    try:
        path = ctypes.util.find_library("System")
        lib = ctypes.CDLL(path) if path else ctypes.CDLL(None)
    except OSError as exc:
        raise BonjourUnavailableError(f"could not load libSystem: {exc}") from exc

    try:
        _bind_signatures(lib)
    except AttributeError as exc:
        raise BonjourUnavailableError(
            f"libSystem is missing a dns_sd symbol: {exc}"
        ) from exc

    _lib_cache = lib
    return _lib_cache


def reset_library() -> None:
    global _lib_cache
    _lib_cache = None


def _bind_signatures(lib) -> None:
    lib.DNSServiceRegister.restype = _DNSServiceErrorType_t
    lib.DNSServiceRegister.argtypes = [
        ctypes.POINTER(_DNSServiceRef_t),
        _DNSServiceFlags_t,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_uint16,
        ctypes.c_uint16,
        ctypes.c_void_p,
        _RegisterReply_t,
        ctypes.c_void_p,
    ]

    lib.DNSServiceBrowse.restype = _DNSServiceErrorType_t
    lib.DNSServiceBrowse.argtypes = [
        ctypes.POINTER(_DNSServiceRef_t),
        _DNSServiceFlags_t,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_char_p,
        _BrowseReply_t,
        ctypes.c_void_p,
    ]

    lib.DNSServiceResolve.restype = _DNSServiceErrorType_t
    lib.DNSServiceResolve.argtypes = [
        ctypes.POINTER(_DNSServiceRef_t),
        _DNSServiceFlags_t,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        _ResolveReply_t,
        ctypes.c_void_p,
    ]

    lib.DNSServiceGetAddrInfo.restype = _DNSServiceErrorType_t
    lib.DNSServiceGetAddrInfo.argtypes = [
        ctypes.POINTER(_DNSServiceRef_t),
        _DNSServiceFlags_t,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_char_p,
        _GetAddrInfoReply_t,
        ctypes.c_void_p,
    ]

    lib.DNSServiceRefSockFD.restype = ctypes.c_int
    lib.DNSServiceRefSockFD.argtypes = [_DNSServiceRef_t]

    lib.DNSServiceProcessResult.restype = _DNSServiceErrorType_t
    lib.DNSServiceProcessResult.argtypes = [_DNSServiceRef_t]

    lib.DNSServiceRefDeallocate.restype = None
    lib.DNSServiceRefDeallocate.argtypes = [_DNSServiceRef_t]




def encode_txt(pairs: List[Tuple[str, str]]) -> bytes:
    out = bytearray()
    for key, value in pairs:
        if "=" in key:
            raise ValueError(f"TXT key {key!r} must not contain '='")
        entry = f"{key}={value}".encode("ascii")
        if len(entry) > 255:
            raise ValueError(f"TXT entry for {key!r} is over 255 bytes")
        out.append(len(entry))
        out.extend(entry)
    return bytes(out)


def decode_txt(data: bytes) -> dict:
    result: dict = {}
    i = 0
    n = len(data)
    while i < n:
        length = data[i]
        i += 1
        if i + length > n:
            break
        entry = data[i:i + length]
        i += length
        if not entry:
            continue
        try:
            text = entry.decode("utf-8", errors="replace")
        except Exception:
            continue
        if "=" in text:
            key, _, value = text.partition("=")
        else:
            key, value = text, ""
        result[key] = value
    return result




class ServiceRef:

    def __init__(self, lib, ref: ctypes.c_void_p, callback) -> None:
        self._lib = lib
        self._ref = ref
        self._callback = callback
        self._deallocated = False

    @property
    def fd(self) -> int:
        return self._lib.DNSServiceRefSockFD(self._ref)

    def process_result(self) -> None:
        """Read and dispatch exactly the one reply already waiting.

        MUST ONLY be called when :attr:`fd` is known readable (an
        ``asyncio`` reader callback firing IS that condition); calling
        it with nothing waiting blocks on the socket.

        Raises: DNSServiceError - the call itself returned non-zero.
          (A non-zero reply *to the registered callback* is reported
          through the callback's own ``errorCode`` argument, not here.)
        """
        rc = self._lib.DNSServiceProcessResult(self._ref)
        if rc != _kDNSServiceErr_NoError:
            raise DNSServiceError(rc, "DNSServiceProcessResult")

    def deallocate(self) -> None:
        if self._deallocated:
            return
        self._lib.DNSServiceRefDeallocate(self._ref)
        self._deallocated = True


def register(
    regtype: str,
    name: str,
    port: int,
    txt: bytes,
    on_reply: Callable[[int, str, str, str], None],
    *,
    interface_index: int = kDNSServiceInterfaceIndexAny,
    flags: int = 0,
    domain: Optional[str] = None,
    loader: Optional[Callable[[], object]] = None,
) -> ServiceRef:
    lib = get_library(loader)
    ref = _DNSServiceRef_t()

    def _trampoline(sd_ref, cb_flags, error_code, c_name, c_regtype, c_domain, context):
        on_reply(
            error_code,
            _decode(c_name),
            _decode(c_regtype),
            _decode(c_domain),
        )

    callback = _RegisterReply_t(_trampoline)
    rc = lib.DNSServiceRegister(
        ctypes.byref(ref),
        flags,
        interface_index,
        name.encode("utf-8"),
        regtype.encode("utf-8"),
        domain.encode("utf-8") if domain else None,
        None,
        socket.htons(port),
        len(txt),
        txt,
        callback,
        None,
    )
    if rc != _kDNSServiceErr_NoError:
        raise DNSServiceError(rc, "DNSServiceRegister")
    return ServiceRef(lib, ref, callback)


def browse(
    regtype: str,
    on_reply: Callable[[int, int, str, str, str], None],
    *,
    interface_index: int = kDNSServiceInterfaceIndexAny,
    flags: int = 0,
    domain: Optional[str] = None,
    loader: Optional[Callable[[], object]] = None,
) -> ServiceRef:
    lib = get_library(loader)
    ref = _DNSServiceRef_t()

    def _trampoline(sd_ref, cb_flags, iface, error_code, c_name, c_regtype, c_domain, context):
        on_reply(
            error_code,
            cb_flags,
            _decode(c_name),
            _decode(c_regtype),
            _decode(c_domain),
        )

    callback = _BrowseReply_t(_trampoline)
    rc = lib.DNSServiceBrowse(
        ctypes.byref(ref),
        flags,
        interface_index,
        regtype.encode("utf-8"),
        domain.encode("utf-8") if domain else None,
        callback,
        None,
    )
    if rc != _kDNSServiceErr_NoError:
        raise DNSServiceError(rc, "DNSServiceBrowse")
    return ServiceRef(lib, ref, callback)


def resolve(
    name: str,
    regtype: str,
    domain: str,
    on_reply: Callable[[int, str, str, int, bytes], None],
    *,
    interface_index: int = kDNSServiceInterfaceIndexAny,
    flags: int = 0,
    loader: Optional[Callable[[], object]] = None,
) -> ServiceRef:
    lib = get_library(loader)
    ref = _DNSServiceRef_t()

    def _trampoline(sd_ref, cb_flags, iface, error_code, c_fullname, c_host,
                     net_port, txt_len, txt_ptr, context):
        txt_bytes = b""
        if txt_ptr and txt_len:
            txt_bytes = bytes(
                ctypes.cast(txt_ptr, ctypes.POINTER(ctypes.c_ubyte * txt_len)).contents
            )
        on_reply(
            error_code,
            _decode(c_fullname),
            _decode(c_host),
            socket.ntohs(net_port),
            txt_bytes,
        )

    callback = _ResolveReply_t(_trampoline)
    rc = lib.DNSServiceResolve(
        ctypes.byref(ref),
        flags,
        interface_index,
        name.encode("utf-8"),
        regtype.encode("utf-8"),
        domain.encode("utf-8"),
        callback,
        None,
    )
    if rc != _kDNSServiceErr_NoError:
        raise DNSServiceError(rc, "DNSServiceResolve")
    return ServiceRef(lib, ref, callback)


def get_addr_info(
    hostname: str,
    on_reply: Callable[[int, str, List[DiscoveredAddress]], None],
    *,
    protocol: int = 0,
    interface_index: int = kDNSServiceInterfaceIndexAny,
    flags: int = 0,
    loader: Optional[Callable[[], object]] = None,
) -> ServiceRef:
    lib = get_library(loader)
    ref = _DNSServiceRef_t()

    def _trampoline(sd_ref, cb_flags, iface, error_code, c_hostname, address_ptr, ttl, context):
        addresses: List[DiscoveredAddress] = []
        parsed = _parse_sockaddr(address_ptr)
        if parsed is not None:
            addresses.append(parsed)
        on_reply(error_code, _decode(c_hostname), addresses)

    callback = _GetAddrInfoReply_t(_trampoline)
    rc = lib.DNSServiceGetAddrInfo(
        ctypes.byref(ref),
        flags,
        interface_index,
        protocol,
        hostname.encode("utf-8"),
        callback,
        None,
    )
    if rc != _kDNSServiceErr_NoError:
        raise DNSServiceError(rc, "DNSServiceGetAddrInfo")
    return ServiceRef(lib, ref, callback)


def _decode(c_str: Optional[bytes]) -> str:
    if not c_str:
        return ""
    return c_str.decode("utf-8", errors="replace")


def _parse_sockaddr(address_ptr) -> Optional[DiscoveredAddress]:
    if not address_ptr:
        return None
    family_byte = ctypes.cast(
        address_ptr, ctypes.POINTER(ctypes.c_uint8 * 2)
    ).contents[1]
    if family_byte == socket.AF_INET:
        sa = ctypes.cast(address_ptr, ctypes.POINTER(_sockaddr_in)).contents
        return DiscoveredAddress(
            address=socket.inet_ntop(socket.AF_INET, bytes(sa.sin_addr)),
            family=socket.AF_INET,
        )
    if family_byte == socket.AF_INET6:
        sa = ctypes.cast(address_ptr, ctypes.POINTER(_sockaddr_in6)).contents
        return DiscoveredAddress(
            address=socket.inet_ntop(socket.AF_INET6, bytes(sa.sin6_addr)),
            family=socket.AF_INET6,
        )
    return None
