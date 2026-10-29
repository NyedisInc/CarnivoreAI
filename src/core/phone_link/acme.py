
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

import httpx
import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

from src.core.phone_link.dns01 import Dns01Error

logger = structlog.get_logger()

POLL_TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30.0
_BAD_NONCE = "urn:ietf:params:acme:error:badNonce"


class AcmeError(Exception):
    pass


class TxtPublisher(Protocol):

    async def publish(self, value: str) -> str: ...

    async def clear(self, value: str) -> None: ...


class AlpnPublisher(Protocol):

    async def publish(self, domain: str, digest: bytes) -> None: ...

    async def clear(self, domain: str) -> None: ...


SHORTLIVED = "shortlived"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def jwk_of(key: ec.EllipticCurvePrivateKey) -> Dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {"crv": "P-256", "kty": "EC", "x": _b64(numbers.x.to_bytes(32, "big")),
            "y": _b64(numbers.y.to_bytes(32, "big"))}


def thumbprint(jwk: Dict[str, str]) -> str:
    canonical = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")},
                           sort_keys=True, separators=(",", ":"))
    return _b64(hashlib.sha256(canonical.encode("ascii")).digest())


def key_authorization_digest(token: str, jwk: Dict[str, str]) -> bytes:
    return hashlib.sha256(f"{token}.{thumbprint(jwk)}".encode("ascii")).digest()


def txt_value(token: str, jwk: Dict[str, str]) -> str:
    return _b64(hashlib.sha256(f"{token}.{thumbprint(jwk)}".encode("ascii")).digest())


def make_csr(hostname: str, key: ec.EllipticCurvePrivateKey) -> bytes:
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
           .sign(key, hashes.SHA256()))
    return csr.public_bytes(serialization.Encoding.DER)


class AcmeClient:

    def __init__(self, *, directory_url: str, account_key: ec.EllipticCurvePrivateKey,
                 dns: Optional[TxtPublisher] = None, alpn: Optional[AlpnPublisher] = None,
                 profile: Optional[str] = None, http: Optional[httpx.AsyncClient] = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        if (dns is None) == (alpn is None):
            raise ValueError("an ACME client needs exactly one of dns and alpn")
        self._directory_url = directory_url
        self._key = account_key
        self._jwk = jwk_of(account_key)
        self._dns = dns
        self._alpn = alpn
        self._profile = profile
        self._http = http or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_http = http is None
        self._sleep = sleep
        self._directory: Dict[str, Any] = {}
        self._nonce: Optional[str] = None
        self._kid: Optional[str] = None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _jws(self, url: str, payload: Optional[Dict[str, Any]], nonce: str) -> Dict[str, str]:
        protected: Dict[str, Any] = {"alg": "ES256", "nonce": nonce, "url": url}
        protected.update({"kid": self._kid} if self._kid else {"jwk": self._jwk})
        head = _b64(json.dumps(protected, separators=(",", ":")).encode())
        body = "" if payload is None else _b64(json.dumps(payload, separators=(",", ":")).encode())
        der = self._key.sign(f"{head}.{body}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        return {"protected": head, "payload": body,
                "signature": _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}

    async def _fresh_nonce(self) -> str:
        try:
            response = await self._http.head(self._directory["newNonce"])
        except httpx.HTTPError as exc:
            raise AcmeError(f"the CA could not be reached: {type(exc).__name__}") from None
        nonce = response.headers.get("replay-nonce")
        if not nonce:
            raise AcmeError("the CA sent no nonce")
        return nonce

    async def _post(self, url: str, payload: Optional[Dict[str, Any]],
                    accept: str = "application/json") -> httpx.Response:
        for attempt in range(2):
            nonce, self._nonce = self._nonce or await self._fresh_nonce(), None
            try:
                response = await self._http.post(
                    url, json=self._jws(url, payload, nonce),
                    headers={"content-type": "application/jose+json", "accept": accept})
            except httpx.HTTPError as exc:
                raise AcmeError(f"the CA could not be reached: {type(exc).__name__}") from None
            self._nonce = response.headers.get("replay-nonce")
            if response.status_code < 400:
                return response
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            kind = str(problem.get("type", f"http_{response.status_code}"))
            if kind == _BAD_NONCE and attempt == 0:
                continue
            raise AcmeError(kind)
        raise AcmeError(_BAD_NONCE)

    async def _poll(self, url: str, done: tuple, what: str) -> Dict[str, Any]:
        waited = 0.0
        while True:
            body = (await self._post(url, None)).json()
            status = body.get("status")
            if status in done:
                return body
            if status == "invalid":
                raise AcmeError(f"{what} became invalid")
            if waited >= POLL_TIMEOUT_SECONDS:
                raise AcmeError(f"{what} did not finish in time")
            await self._sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS

    async def _prove(self, authz_url: str) -> None:
        authz = (await self._post(authz_url, None)).json()
        if authz.get("status") == "valid":
            return
        if self._alpn is not None:
            await self._prove_alpn(authz_url, authz)
            return
        assert self._dns is not None
        challenge = next((c for c in authz.get("challenges", []) if c.get("type") == "dns-01"), None)
        if challenge is None:
            raise AcmeError("the CA offered no dns-01 challenge")
        value = txt_value(challenge["token"], self._jwk)
        try:
            await self._dns.publish(value)
            await self._post(challenge["url"], {})
            await self._poll(authz_url, ("valid",), "the authorization")
        finally:
            try:
                await self._dns.clear(value)
            except Dns01Error as exc:
                logger.warning("phone_link_acme_txt_clear_failed", error=str(exc))

    async def _prove_alpn(self, authz_url: str, authz: Dict[str, Any]) -> None:
        assert self._alpn is not None
        challenge = next((c for c in authz.get("challenges", []) if c.get("type") == "tls-alpn-01"), None)
        if challenge is None:
            raise AcmeError("the CA offered no tls-alpn-01 challenge")
        domain = str(authz["identifier"]["value"])
        await self._alpn.publish(domain, key_authorization_digest(challenge["token"], self._jwk))
        try:
            await self._post(challenge["url"], {})
            await self._poll(authz_url, ("valid",), "the authorization")
        finally:
            await self._alpn.clear(domain)

    async def _open_directory(self) -> None:
        response = await self._http.get(self._directory_url)
        if response.status_code != 200:
            raise AcmeError("the ACME directory did not answer")
        self._directory = response.json()
        self._nonce, self._kid = None, None
        account = await self._post(self._directory["newAccount"], {"termsOfServiceAgreed": True})
        self._kid = account.headers["location"]

    async def account_uri(self) -> str:
        try:
            await self._open_directory()
        except httpx.HTTPError as exc:
            raise AcmeError(f"the CA could not be reached: {type(exc).__name__}") from None
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise AcmeError(f"the CA sent an unexpected answer: {type(exc).__name__}") from None
        assert self._kid is not None
        return self._kid

    async def obtain(self, hostname: str, cert_key: ec.EllipticCurvePrivateKey) -> str:
        try:
            return await self._obtain(hostname, cert_key)
        except httpx.HTTPError as exc:
            raise AcmeError(f"the CA could not be reached: {type(exc).__name__}") from None
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise AcmeError(f"the CA sent an unexpected answer: {type(exc).__name__}") from None

    async def _obtain(self, hostname: str, cert_key: ec.EllipticCurvePrivateKey) -> str:
        await self._open_directory()
        order_body: Dict[str, Any] = {"identifiers": [{"type": "dns", "value": hostname}]}
        if self._profile:
            if self._profile not in (self._directory.get("meta", {}).get("profiles") or {}):
                raise AcmeError(f"the CA does not offer the {self._profile} profile")
            order_body["profile"] = self._profile
        order_resp = await self._post(self._directory["newOrder"], order_body)
        order, order_url = order_resp.json(), order_resp.headers["location"]
        for authz_url in order["authorizations"]:
            await self._prove(authz_url)
        await self._poll(order_url, ("ready", "valid"), "the order")
        await self._post(order["finalize"], {"csr": _b64(make_csr(hostname, cert_key))})
        done = await self._poll(order_url, ("valid",), "the order")
        chain = await self._post(done["certificate"], None, "application/pem-certificate-chain")
        logger.info("phone_link_certificate_issued")
        return chain.text
