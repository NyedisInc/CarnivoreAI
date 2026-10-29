
from __future__ import annotations

import binascii
import ipaddress
import re
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.computers import join_proto
from src.core.computers.join_proto import JoinKeys, ProtoError
from src.core.relay_identity.device_key import DeviceKey, device_id_for, unb64url

MAX_INSTALL_ID = 64
MAX_LISTEN_ADDRESSES = 8
_LOCAL_NAME = re.compile(r"^[A-Za-z0-9-]{1,63}\.local$")


def build_identity(*, role: str, t: bytes, keys: JoinKeys, key: DeviceKey, install_id: str, label: str, public_key: str,
                   cert_der: bytes, grant_id: str, app_version: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "install_id": install_id, "label": label[:64], "public_key": public_key, "fid": key.device_id, "grant_id": grant_id,
        "cert_der": join_proto.b64e(cert_der), "protocol": join_proto.PROTOCOL_VERSION, "app_version": app_version[:64],
        "capabilities": [], **(extra or {}),
    }
    body["sig"] = key.sign(join_proto.identity_sig_input(role, t, cert_der, grant_id))
    return join_proto.sign_identity(body, keys, role)


def verify_identity(msg: Dict[str, Any], *, t: bytes, keys: JoinKeys, sender_role: str) -> Tuple[Dict[str, Any], bytes]:
    body = join_proto.check_identity(msg, keys, sender_role)
    if len(body["install_id"]) > MAX_INSTALL_ID or not body["install_id"]:
        raise ProtoError("install id malformed")
    raw_pub = unb64url(body["public_key"], 32)
    if raw_pub is None or device_id_for(raw_pub) != body["fid"]:
        raise ProtoError("public key does not match its fid")
    cert_der = join_proto.b64d(body["cert_der"], field="cert_der")
    sig = unb64url(body["sig"], 64)
    if sig is None:
        raise ProtoError("signature malformed")
    try:
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(sig, join_proto.identity_sig_input(sender_role, t, cert_der, body["grant_id"]))
    except (InvalidSignature, ValueError, binascii.Error):
        raise ProtoError("identity signature invalid") from None
    return body, cert_der


def lan_address_ok(text: str, *, lan_only: bool = True) -> bool:
    if _LOCAL_NAME.fullmatch(text):
        return True
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return ip.version == 4 and not (ip.is_unspecified or ip.is_multicast or ip.is_link_local or (lan_only and ip.is_loopback))


def listen_of(body: Dict[str, Any], *, join_port: int, lan_only: bool = True) -> Tuple[List[str], int]:
    listen = body.get("listen")
    if not isinstance(listen, dict):
        raise ProtoError("listen data missing")
    addrs, port = listen.get("addresses"), listen.get("port")
    if (not isinstance(addrs, list) or not 1 <= len(addrs) <= MAX_LISTEN_ADDRESSES
            or any(not isinstance(a, str) or not lan_address_ok(a, lan_only=lan_only) for a in addrs)):
        raise ProtoError("listen addresses malformed")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535 or port == join_port:
        raise ProtoError("listen port malformed")
    names = [a for a in dict.fromkeys(addrs) if a.lower().endswith(".local")]
    return names + [a for a in dict.fromkeys(addrs) if a not in names], port
