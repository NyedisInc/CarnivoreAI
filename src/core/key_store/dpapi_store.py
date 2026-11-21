
from __future__ import annotations

import ctypes
import sys
from typing import Optional, Tuple

import structlog

from src.core import relay_keychain
from src.core.key_store import file_store

logger = structlog.get_logger()

_ENTROPY = b"carnivore key store v1"

_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):

    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(protect: bool, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI exists only on Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
    fn.restype = ctypes.c_int
    src_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    src = _DataBlob(len(data), ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_char)))
    ent = _DataBlob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out))
    ctypes.memset(src_buf, 0, len(data))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def read_state(service: str, account: str) -> Tuple[str, Optional[str]]:
    target = file_store.target_for(service, account)
    if target is None:
        return relay_keychain.READ_UNAVAILABLE, None
    state, blob = file_store.read_blob(*target)
    if state != relay_keychain.READ_OK or blob is None:
        return state, None
    try:
        return relay_keychain.READ_OK, _crypt(False, blob).decode("ascii")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("key_store_dpapi_unreadable", why=type(exc).__name__)
        return relay_keychain.READ_UNAVAILABLE, None


def write(service: str, account: str, secret: str, replace: bool) -> None:
    target = file_store.target_for(service, account)
    if target is None or not relay_keychain.is_safe_secret(secret):
        raise relay_keychain.KeychainWriteError("the item name or value is not storable")
    try:
        blob = _crypt(True, secret.encode("ascii"))
    except OSError as exc:
        raise relay_keychain.KeychainWriteError(type(exc).__name__) from None
    file_store.write_blob(target[0], target[1], blob, replace)


def delete(service: str, account: str) -> bool:
    target = file_store.target_for(service, account)
    return target is not None and file_store.delete_blob(*target)
