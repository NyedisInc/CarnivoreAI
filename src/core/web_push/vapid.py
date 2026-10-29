
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

logger = structlog.get_logger()

KEY_FILE = "web_push_vapid.pem"
DEFAULT_SUBJECT = "https://carnivore.ai"
JWT_LIFETIME_SECONDS = 12 * 3600
CONFIG_KEY = "web_push"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not text.isascii():
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise ValueError("not base64url") from exc


def load_or_create_key(state_dir: Path) -> ec.EllipticCurvePrivateKey:
    path = Path(state_dir) / KEY_FILE
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
            raise ValueError("the stored VAPID key is not a P-256 key")
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_or_create_key(state_dir)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(pem)
    logger.info("web_push_vapid_key_created")
    return key


def public_key_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key_b64(state_dir: Path) -> str:
    return b64url(public_key_bytes(load_or_create_key(state_dir)))


def valid_subject(subject: Any) -> bool:
    if not isinstance(subject, str) or len(subject) > 200:
        return False
    if subject.startswith("mailto:"):
        local, _, domain = subject[7:].partition("@")
        return bool(local and domain)
    parts = urlsplit(subject)
    return parts.scheme == "https" and bool(parts.hostname)


def subject_from_config(config_path: Path) -> str:
    try:
        data = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        subject = (data.get(CONFIG_KEY) or {}).get("subject")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_SUBJECT
    return subject if valid_subject(subject) else DEFAULT_SUBJECT


def origin_of(endpoint: str) -> str:
    return f"https://{(urlsplit(endpoint).hostname or '').lower()}"


def sign_jwt(key: ec.EllipticCurvePrivateKey, audience: str, subject: str, *, now: Optional[float] = None,
             lifetime: int = JWT_LIFETIME_SECONDS) -> str:
    issued = int(time.time() if now is None else now)
    claims: Dict[str, Any] = {"aud": audience, "exp": issued + min(lifetime, JWT_LIFETIME_SECONDS), "sub": subject}
    head = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{body}".encode("ascii"), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{body}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def authorization_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str) -> str:
    return f"vapid t={sign_jwt(key, origin_of(endpoint), subject)}, k={b64url(public_key_bytes(key))}"
