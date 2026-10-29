
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from src.core.phone_link import acme

logger = structlog.get_logger()

RENEW_BEFORE_DAYS = 30
CHECK_INTERVAL_SECONDS = 6 * 3600.0
RETRY_SECONDS = 3600.0

Obtain = Callable[[str, ec.EllipticCurvePrivateKey], Awaitable[str]]


def write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def link_hostname(device_id: str, domain: str) -> str:
    return f"{device_id}.{domain}"


def describe_cert(directory: Path) -> Optional[Dict[str, str]]:
    directory = Path(directory)
    try:
        cert = x509.load_pem_x509_certificate((directory / "cert.pem").read_bytes())
        meta = json.loads((directory / "cert.json").read_text())
    except (OSError, ValueError):
        return None
    names = cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    issuer = str(names[0].value) if names else ""
    staging = "staging" in str(meta.get("directory", "")) if isinstance(meta, dict) else False
    described = {"issuer": issuer, "not_after": cert.not_valid_after_utc.isoformat(),
                 "environment": "staging" if staging else "production"}
    if isinstance(meta, dict) and isinstance(meta.get("profile"), str):
        described["profile"] = meta["profile"]
    return described


def install_sni_selector(link_context: ssl.SSLContext, custom: Callable[[], Optional[Tuple[str, ssl.SSLContext]]]) -> None:
    def pick(ssl_object: Any, server_name: Optional[str], _context: ssl.SSLContext) -> None:
        chosen = custom()
        if chosen is not None and server_name and server_name.lower().rstrip(".") == chosen[0]:
            ssl_object.context = chosen[1]

    link_context.sni_callback = pick


class CertManager:

    def __init__(self, *, directory: Path, directory_url: str, obtain: Obtain,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 renew_before: timedelta = timedelta(days=RENEW_BEFORE_DAYS),
                 meta: Optional[Dict[str, str]] = None,
                 account_key_path: Optional[Path] = None) -> None:
        self._account_key_path = account_key_path
        self._renew_before = renew_before
        self._extra_meta = dict(meta or {})
        self._dir = Path(directory)
        self._directory_url = directory_url
        self._obtain = obtain
        self._clock = clock
        self._context: Optional[ssl.SSLContext] = None
        self._task: Optional["asyncio.Task[None]"] = None
        self.hostname = ""

    @property
    def cert_path(self) -> Path:
        return self._dir / "cert.pem"

    @property
    def key_path(self) -> Path:
        return self._dir / "cert.key"

    @property
    def account_key_path(self) -> Path:
        return self._account_key_path or self._dir / "account.key"

    def _prepare(self) -> None:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._dir, 0o700)

    def load_or_create_key(self, path: Path) -> ec.EllipticCurvePrivateKey:
        self._prepare()
        if path.exists():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError("the stored key is not an EC key")
            return key
        key = acme.new_ec_key()
        write_private(path, key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        return key

    def not_after(self) -> Optional[datetime]:
        try:
            cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        except (OSError, ValueError):
            return None
        return cert.not_valid_after_utc

    def _meta_matches(self, hostname: str) -> bool:
        try:
            meta = json.loads((self._dir / "cert.json").read_text())
        except (OSError, ValueError):
            return False
        return meta.get("hostname") == hostname and meta.get("directory") == self._directory_url

    def needs_renewal(self, hostname: str) -> bool:
        expiry = self.not_after()
        return (expiry is None or not self._meta_matches(hostname)
                or expiry - self._clock() < self._renew_before)

    def context(self) -> ssl.SSLContext:
        if self._context is None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.set_alpn_protocols(["http/1.1"])
            self._context = ctx
        self._context.load_cert_chain(str(self.cert_path), str(self.key_path))
        return self._context

    def context_loaded(self) -> ssl.SSLContext:
        if self._context is None:
            raise RuntimeError("no certificate context is loaded")
        return self._context

    def forget(self) -> None:
        for path in (self.cert_path, self.key_path, self._dir / "cert.json"):
            with contextlib.suppress(OSError):
                path.unlink()
        self._context = None

    async def ensure(self, hostname: str) -> ssl.SSLContext:
        self.hostname = hostname
        if await asyncio.to_thread(self.needs_renewal, hostname):
            try:
                await self.renew(hostname)
            except (acme.AcmeError, acme.Dns01Error) as exc:
                if not await asyncio.to_thread(self.is_usable, hostname):
                    raise
                logger.warning("phone_link_renewal_failed_using_stored", error=str(exc))
        return await asyncio.to_thread(self.context)

    def is_usable(self, hostname: str) -> bool:
        expiry = self.not_after()
        return expiry is not None and self._meta_matches(hostname) and expiry > self._clock()

    async def renew(self, hostname: str) -> None:
        key = await asyncio.to_thread(self.load_or_create_key, self.key_path)
        pem = await self._obtain(hostname, key)

        def store() -> None:
            write_private(self.cert_path, pem.encode("ascii"))
            write_private(self._dir / "cert.json", json.dumps(
                {"hostname": hostname, "directory": self._directory_url, **self._extra_meta}).encode())

        await asyncio.to_thread(store)
        if self._context is not None:
            self.context()
        logger.info("phone_link_certificate_stored")

    def start_renewals(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._renew_loop(), name="phone-link-renew")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _renew_loop(self) -> None:
        wait = CHECK_INTERVAL_SECONDS
        while True:
            await asyncio.sleep(wait)
            wait = CHECK_INTERVAL_SECONDS
            if not self.hostname or not await asyncio.to_thread(self.needs_renewal, self.hostname):
                continue
            try:
                await self.renew(self.hostname)
            except Exception as exc:  # noqa: BLE001
                logger.warning("phone_link_renewal_failed", error_type=type(exc).__name__, error=str(exc)[:200])
                wait = RETRY_SECONDS
