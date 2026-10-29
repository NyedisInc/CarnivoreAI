
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from relay.auth import DENYLIST_TYP, TOKEN_TYP, b64url, device_id_for, pop_message
from relay.protocol import PUBLISH_SUBPROTOCOL_V2, WATCH_SUBPROTOCOL, link_id_v2
from src.core import relay_e2ee
from src.core.spectator_redaction import Scrubbed, SpectatorScrubber

KID = "rt1"
DEFAULT_LIM = {"links": 5, "pubs": 2, "wpl": 16, "bps": 262144,
               "burst": 1048576, "bytes_day": 2147483648}


def raw_pub(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)


class Issuer:

    def __init__(self, kid: str = KID) -> None:
        self.kid = kid
        self.key = Ed25519PrivateKey.generate()

    @property
    def pins(self) -> Dict[str, bytes]:
        return {self.kid: raw_pub(self.key)}

    def jws(self, typ: str, payload: Dict[str, Any], header: Optional[bytes] = None) -> str:
        head = header or f'{{"alg":"EdDSA","kid":"{self.kid}","typ":"{typ}"}}'.encode()
        head_b64 = b64url(head)
        body_b64 = b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signing = f"{head_b64}.{body_b64}".encode()
        return f"{head_b64}.{body_b64}.{b64url(self.key.sign(signing))}"

    def token(self, device: "Device", **overrides: Any) -> str:
        now = int(time.time())
        claims = {"iss": "api.carnivore.ai", "aud": "relay.carnivore.ai",
                  "sub": device.device_id, "dpk": b64url(device.pub), "ten": device.ten,
                  "iat": now, "nbf": now - 30, "exp": now + 900,
                  "jti": b64url(secrets.token_bytes(16)), "lim": dict(DEFAULT_LIM),
                  "min": "0.0.0", "v": 2}
        header = overrides.pop("header", None)
        claims.update(overrides)
        return self.jws(TOKEN_TYP, claims, header)

    def denylist(self, seq: int, entries: List[dict]) -> dict:
        page = {"seq": seq, "issued_at": int(time.time()), "page": 1, "pages": 1,
                "entries": entries}
        return {"denylist": [self.jws(DENYLIST_TYP, page)]}


class Device:

    def __init__(self, ten: Optional[str] = None) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.pub = raw_pub(self.key)
        self.device_id = device_id_for(self.pub)
        self.ten = ten or b64url(secrets.token_bytes(16))

    def pop(self, token: str, ts: Optional[int] = None) -> Dict[str, str]:
        jti = json.loads(_payload(token))["jti"]
        moment = int(time.time()) if ts is None else ts
        return {"carnivore-relay-pop-ts": str(moment),
                "carnivore-relay-pop": b64url(self.key.sign(pop_message(jti, moment)))}

    def headers(self, token: str, client: str = "1.8.1", ts: Optional[int] = None) -> Dict[str, str]:
        return {"authorization": f"Bearer {token}", "carnivore-relay-client": client,
                **self.pop(token, ts)}

    def reauth(self, token: str) -> dict:
        pop = self.pop(token)
        return {"type": "reauth", "token": token, "pop_ts": int(pop["carnivore-relay-pop-ts"]),
                "pop": pop["carnivore-relay-pop"]}

    def link(self, nonce: Optional[bytes] = None) -> tuple:
        raw = nonce or secrets.token_bytes(16)
        return link_id_v2(self.device_id, raw), b64url(raw)


def _payload(token: str) -> bytes:
    import base64

    body = token.split(".")[1]
    return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))


V2_TOKEN = relay_e2ee.b64url(secrets.token_bytes(32))


def links_v2(entries: Dict[str, str], nonces: Dict[str, str]) -> dict:
    return {"type": "links", "links": [
        {"link_id": link_id,
         "token_sha256": relay_e2ee.derive_link_keys(tok, link_id).verifier,
         "nonce": nonces[link_id]}
        for link_id, tok in entries.items()]}


def watch_v2(link_id: str, token: str = V2_TOKEN) -> List[str]:
    keys = relay_e2ee.derive_link_keys(token, link_id)
    return [WATCH_SUBPROTOCOL, b64url(keys.watch_auth)]


class _Echo:

    stats = type("Stats", (), {"chunks_in": 0, "findings": 0, "detectors": ()})()

    def feed(self, chunk: str) -> str:
        return chunk

    def flush(self) -> str:
        return ""


def scrubbed(data: bytes) -> Scrubbed:
    return SpectatorScrubber(_Echo(), label="test").scrub(data)


class SealedLink:

    def __init__(self, link_id: str, token: str = V2_TOKEN, expires_in: int = 3600) -> None:
        self.link_id = link_id
        self.keys = relay_e2ee.derive_link_keys(token, link_id)
        self.sealer = relay_e2ee.Sealer(link_id, self.keys.content_key)
        self.expires_at = int(time.time()) + expires_in

    def open(self, cols: int = 80, rows: int = 24) -> bytes:
        return relay_e2ee.record_frame(self.link_id, self.sealer.open(
            expires_at=self.expires_at, scrubber="0123456789ab", client_version="1.9.0",
            cols=cols, rows=rows))

    def data(self, text: str) -> List[bytes]:
        return [relay_e2ee.record_frame(self.link_id, rec)
                for rec in self.sealer.data(scrubbed(text.encode()))]

    def read(self, record: bytes) -> relay_e2ee.OpenedRecord:
        return relay_e2ee.open_record(self.keys.content_key, self.link_id, record)


V2 = [PUBLISH_SUBPROTOCOL_V2]
