
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog

from src.core.computers import link_rotate
from src.core.federation import fed_key
from src.core.federation.grants import Grant, GrantError, decode_public_key
from src.core.relay_identity.device_key import DeviceKey, b64url, unb64url

logger = structlog.get_logger()

class RotationBusy(RuntimeError):
    pass


_rotation_lock = asyncio.Lock()

ANNOUNCE_PREFIX = b"carnivore federation v1 key-rotate\x00"
ANNOUNCE_PATH = "/federation/key/announce"


def announce_message(sender_install_id: str, receiver_grant_id: str, old_raw: bytes, new_raw: bytes) -> bytes:
    return (ANNOUNCE_PREFIX + sender_install_id.encode() + b"\x00" + receiver_grant_id.encode() + b"\x00"
            + old_raw + new_raw)


def verify_announcement(grant: Grant, new_public_key: str, signature: object) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    new_raw, old_raw = decode_public_key(new_public_key), decode_public_key(grant.public_key)
    sig = unb64url(signature, 64)
    if sig is None:
        raise GrantError("rotation_refused", "the announcement was not accepted")
    message = announce_message(grant.peer_install_id, grant.grant_id, old_raw, new_raw)
    try:
        Ed25519PublicKey.from_public_bytes(old_raw).verify(sig, message)
    except InvalidSignature:
        raise GrantError("rotation_refused", "the announcement was not accepted") from None


async def rotate(*, install_id: str, links: Any, live_grants: int) -> Dict[str, Any]:
    if _rotation_lock.locked():
        raise RotationBusy("a key rotation is already running")
    async with _rotation_lock:
        return await _rotate_locked(install_id=install_id, links=links, live_grants=live_grants)


async def _rotate_locked(*, install_id: str, links: Any, live_grants: int) -> Dict[str, Any]:
    old: DeviceKey = await asyncio.to_thread(fed_key.load_key, install_id)
    new: DeviceKey = await asyncio.to_thread(fed_key.begin_rotation, install_id)
    new_pub = fed_key.public_key_b64(new)
    told: List[str] = []
    for peer, client in (links.connected_clients() if links is not None else []):
        signature = old.sign(announce_message(install_id, client.grant_id, old.raw_pub, new.raw_pub))
        try:
            response = await client.request("POST", ANNOUNCE_PATH, json={"new_public_key": new_pub,
                                                                       "signature": signature})
        except Exception as exc:  # noqa: BLE001
            logger.warning("federation_key_announce_failed", peer=peer[:8], error_type=type(exc).__name__)
            continue
        if response.status_code == 200:
            told.append(peer)
        else:
            logger.warning("federation_key_announce_refused", peer=peer[:8], status=response.status_code)
    await asyncio.to_thread(fed_key.commit_rotation, install_id)
    if links is not None:
        links.use_key(new)
    await link_rotate.after_federation_rotation(new)
    logger.info("federation_key_rotated", fid=fed_key.fid_for(new.raw_pub), announced=len(told))
    return {"fid": fed_key.fid_for(new.raw_pub), "announced": len(told), "not_announced": max(live_grants - len(told), 0)}
