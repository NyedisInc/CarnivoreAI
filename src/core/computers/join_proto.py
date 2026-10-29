
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import struct
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL_VERSION = 2
MAGIC = b"CJOIN\x00\x01\x00"
MAX_MESSAGE = 16384
TLS_HANDSHAKE_TIMEOUT = 5.0
FIRST_MESSAGE_TIMEOUT = 2.0
MESSAGE_TIMEOUT = 10.0
SESSION_TIMEOUT = 30.0

ID_JOINER = b"carnivore-joiner"
ID_MAIN = b"carnivore-main"
_PW_CODE = b"carnivore join v1 code\x00"
_PW_INVITE = b"carnivore join v1 invite\x00"
_LABEL = b"carnivore join v1"
_CONFIRM_INFO = b"carnivore join v1 confirm"
_SIG_PREFIX = b"carnivore federation v1 join-identity\x00"

MODES = ("code", "invite")
ERROR_CODES = ("wrong_code", "expired", "no_invite", "busy", "rate_limited", "refused", "incompatible")
ABORT_CODES = ("main_mismatch", "refused", "needs_owner", "join_has_peers")


class ProtoError(ValueError):
    pass


class Incompatible(ProtoError):
    pass


class SpakeUnavailable(RuntimeError):
    """The ``spake2`` package is not installed in this venv."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def lp(data: bytes) -> bytes:
    if len(data) > 0xFFFF:
        raise ProtoError("field too long")
    return struct.pack(">H", len(data)) + data


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: Any, *, field: str = "field") -> bytes:
    if not isinstance(text, str):
        raise ProtoError(f"{field} is not text")
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        raise ProtoError(f"{field} is not base64") from None


def password(mode: str, *, code: Optional[str] = None, secret: Optional[bytes] = None) -> bytes:
    if mode == "code":
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ProtoError("code must be six digits")
        return _PW_CODE + code.encode("ascii")
    if mode == "invite":
        if not isinstance(secret, (bytes, bytearray)) or not secret:
            raise ProtoError("invite secret missing")
        return _PW_INVITE + bytes(secret)
    raise ProtoError("unknown mode")


def transcript(*, mode: str, invite_id: str, msg_a: bytes, msg_b: bytes, join_id: str,
               fps: bytes, joiner_fid: str) -> bytes:
    h = hashlib.sha256()
    for part in (_LABEL, mode.encode(), (invite_id or "").encode(), msg_a, msg_b,
                 join_id.encode(), fps, joiner_fid.encode()):
        h.update(lp(part))
    return h.digest()


def fp_server(cert_der: bytes) -> bytes:
    return hashlib.sha256(cert_der).digest()


class JoinKeys:

    def __init__(self, shared_key: bytes, t: bytes) -> None:
        okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=t, info=_CONFIRM_INFO).derive(shared_key)
        self._kc_j, self._kc_m = okm[:32], okm[32:]
        self._t = t

    @staticmethod
    def _mac(key: bytes, *parts: bytes) -> bytes:
        return hmac.new(key, b"".join(parts), hashlib.sha256).digest()

    @staticmethod
    def _digest(obj: Dict[str, Any]) -> bytes:
        return hashlib.sha256(canonical_json(obj)).digest()

    def mac_j(self) -> bytes:
        return self._mac(self._kc_j, b"J", self._t)

    def mac_m(self, main_obj: Dict[str, Any]) -> bytes:
        return self._mac(self._kc_m, b"M", self._t, self._digest(main_obj))

    def mac_identity(self, role: str, body: Dict[str, Any]) -> bytes:
        if role not in ("J", "M"):
            raise ProtoError("unknown role")
        bare = {k: v for k, v in body.items() if k != "mac"}
        key = self._kc_j if role == "J" else self._kc_m
        return self._mac(key, role.encode() + b"-id", self._t, self._digest(bare))

    @staticmethod
    def equal(a: bytes, b: bytes) -> bool:
        return hmac.compare_digest(a, b)


class JoinPake:

    def __init__(self, role: str, pw: bytes) -> None:
        try:
            import spake2
        except ImportError:
            raise SpakeUnavailable("the spake2 package is not installed") from None
        if role == "joiner":
            self._s = spake2.SPAKE2_A(pw, idA=ID_JOINER, idB=ID_MAIN)
        elif role == "main":
            self._s = spake2.SPAKE2_B(pw, idA=ID_JOINER, idB=ID_MAIN)
        else:
            raise ProtoError("unknown role")

    def start(self) -> bytes:
        return self._s.start()

    def finish(self, peer_msg: bytes) -> bytes:
        try:
            return self._s.finish(peer_msg)
        except Exception as exc:
            raise ProtoError("bad spake message") from exc


def identity_sig_input(role: str, t: bytes, cert_der: bytes, grant_id: str) -> bytes:
    if role not in ("J", "M"):
        raise ProtoError("unknown role")
    return _SIG_PREFIX + role.encode() + t + hashlib.sha256(cert_der).digest() + grant_id.encode()



def encode_message(obj: Dict[str, Any]) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        raise ProtoError("message too large")
    return struct.pack(">I", len(body)) + body


def parse_message(body: bytes) -> Dict[str, Any]:
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtoError("not json") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
        raise ProtoError("not a message")
    return obj


async def read_magic(reader: asyncio.StreamReader, timeout: float) -> None:
    try:
        got = await asyncio.wait_for(reader.readexactly(len(MAGIC)), timeout)
    except asyncio.IncompleteReadError:
        raise ProtoError("short magic") from None
    if got != MAGIC:
        raise ProtoError("bad magic")


async def read_message(reader: asyncio.StreamReader, timeout: float) -> Dict[str, Any]:
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout)
        (length,) = struct.unpack(">I", header)
        if length > MAX_MESSAGE:
            raise ProtoError("message too large")
        body = await asyncio.wait_for(reader.readexactly(length), timeout)
    except asyncio.IncompleteReadError:
        raise ProtoError("connection closed mid message") from None
    return parse_message(body)


async def write_message(writer: asyncio.StreamWriter, obj: Dict[str, Any]) -> None:
    writer.write(encode_message(obj))
    await writer.drain()



def _need(msg: Dict[str, Any], key: str, kind: type, *, max_len: int = 4096) -> Any:
    val = msg.get(key)
    if not isinstance(val, kind) or isinstance(val, bool) and kind is not bool:
        raise ProtoError(f"{key} missing or wrong type")
    if isinstance(val, str) and len(val) > max_len:
        raise ProtoError(f"{key} too long")
    return val


def hello(*, mode: str, msg_a: bytes, fid: str, invite_id: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"t": "hello", "v": PROTOCOL_VERSION, "mode": mode, "msg": b64e(msg_a), "fid": fid}
    if invite_id is not None:
        out["invite_id"] = invite_id
    return out


def check_hello(msg: Dict[str, Any]) -> Dict[str, Any]:
    if msg.get("t") != "hello":
        raise ProtoError("not a hello")
    if msg.get("v") != PROTOCOL_VERSION:
        raise Incompatible("hello of another protocol version")
    mode = _need(msg, "mode", str, max_len=8)
    if mode not in MODES:
        raise ProtoError("unknown mode")
    invite_id = msg.get("invite_id")
    if mode == "invite":
        if not isinstance(invite_id, str) or not invite_id or len(invite_id) > 32:
            raise ProtoError("invite id missing")
    elif invite_id is not None:
        raise ProtoError("code mode takes no invite id")
    return {"mode": mode, "invite_id": invite_id, "msg_a": b64d(msg.get("msg"), field="msg"),
            "fid": _need(msg, "fid", str, max_len=64)}


def spake(*, msg_b: bytes, join_id: str) -> Dict[str, Any]:
    return {"t": "spake", "msg": b64e(msg_b), "join_id": join_id}


def check_spake(msg: Dict[str, Any]) -> Dict[str, Any]:
    if msg.get("t") != "spake":
        raise ProtoError("not a spake message")
    join_id = _need(msg, "join_id", str, max_len=16)
    if len(join_id) != 16 or any(c not in "0123456789abcdef" for c in join_id):
        raise ProtoError("bad join id")
    return {"msg_b": b64d(msg.get("msg"), field="msg"), "join_id": join_id}


def confirm_j(mac: bytes) -> Dict[str, Any]:
    return {"t": "confirm", "mac": b64e(mac)}


def confirm_m(main_obj: Dict[str, Any], mac: bytes) -> Dict[str, Any]:
    return {"t": "confirm", "main": main_obj, "mac": b64e(mac)}


def check_confirm(msg: Dict[str, Any], *, from_main: bool) -> Dict[str, Any]:
    if msg.get("t") != "confirm":
        raise ProtoError("not a confirm message")
    out: Dict[str, Any] = {"mac": b64d(msg.get("mac"), field="mac")}
    if from_main:
        main = msg.get("main")
        if not isinstance(main, dict):
            raise ProtoError("main object missing")
        out["main"] = {"install_id": _need(main, "install_id", str, max_len=64),
                       "fid": _need(main, "fid", str, max_len=64)}
        if set(main) != {"install_id", "fid"}:
            raise ProtoError("unexpected fields in main object")
    return out


def error(code: str, left: Optional[int] = None) -> Dict[str, Any]:
    if code not in ERROR_CODES:
        raise ProtoError("unknown error code")
    out: Dict[str, Any] = {"t": "error", "code": code}
    if left is not None:
        out["left"] = left
    return out


def abort(code: str) -> Dict[str, Any]:
    if code not in ABORT_CODES:
        raise ProtoError("unknown abort code")
    return {"t": "abort", "code": code}


def done() -> Dict[str, Any]:
    return {"t": "done"}


def sign_identity(body: Dict[str, Any], keys: JoinKeys, role: str) -> Dict[str, Any]:
    return {**{k: v for k, v in body.items() if k != "mac"}, "t": "identity",
            "mac": b64e(keys.mac_identity(role, {**body, "t": "identity"}))}


def check_identity(msg: Dict[str, Any], keys: JoinKeys, role: str) -> Dict[str, Any]:
    if msg.get("t") != "identity":
        raise ProtoError("not an identity message")
    mac = b64d(msg.get("mac"), field="mac")
    if not keys.equal(mac, keys.mac_identity(role, msg)):
        raise ProtoError("identity mac mismatch")
    for key in ("install_id", "public_key", "fid", "grant_id", "cert_der", "sig"):
        _need(msg, key, str)
    _need(msg, "label", str, max_len=64)
    if not isinstance(msg.get("protocol"), int) or isinstance(msg.get("protocol"), bool):
        raise ProtoError("protocol missing")
    return {k: v for k, v in msg.items() if k != "mac"}
