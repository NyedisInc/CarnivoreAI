
import base64
import json
import os
import ssl
import stat
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

from src.core.phone_link import acme, certs

HOST = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"
BASE = "https://ca.test"


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeDns:

    def __init__(self):
        self.events, self.live = [], set()

    async def publish(self, value):
        self.events.append(("set", value))
        self.live.add(value)
        return "C1"

    async def clear(self, value):
        self.events.append(("clear", value))
        self.live.discard(value)


class FakeCa:

    def __init__(self, days=90):
        self.days, self.nonces, self.n = days, set(), 0
        self.ca_key = ec.generate_private_key(ec.SECP256R1())
        self.jwk = None
        self.state = {"challenge": "pending", "order": "pending"}
        self.cert_pem = ""
        self.bad_nonce_once = False
        self.token = "tok-" + "A" * 20
        self.orders = 0

    def nonce(self):
        self.n += 1
        value = f"n{self.n}"
        self.nonces.add(value)
        return value

    def reply(self, status, body=None, **headers):
        headers["replay-nonce"] = self.nonce()
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    def check_jws(self, request):
        jws = json.loads(request.content)
        protected = json.loads(unb64(jws["protected"]))
        assert protected["alg"] == "ES256" and protected["url"] == str(request.url)
        if protected["nonce"] not in self.nonces:
            return None, None
        self.nonces.discard(protected["nonce"])
        if "jwk" in protected:
            self.jwk = protected["jwk"]
        else:
            assert protected["kid"] == f"{BASE}/acct/1"
        jwk = self.jwk
        x, y = (int.from_bytes(unb64(jwk[k]), "big") for k in ("x", "y"))
        public = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        sig = unb64(jws["signature"])
        assert len(sig) == 64
        public.verify(utils.encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                      f"{jws['protected']}.{jws['payload']}".encode(), ec.ECDSA(hashes.SHA256()))
        payload = json.loads(unb64(jws["payload"])) if jws["payload"] else None
        return protected, payload

    def sign(self, csr_der):
        csr = x509.load_der_x509_csr(csr_der)
        assert csr.is_signature_valid
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        assert san == [HOST]
        now = datetime.now(timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake ca")])
        cert = (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(name)
                .public_key(csr.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=self.days))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
                .sign(self.ca_key, hashes.SHA256()))
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    def handler(self, request):
        url = str(request.url)
        if request.method == "GET":
            return httpx.Response(200, json={"newNonce": f"{BASE}/nonce", "newAccount": f"{BASE}/acct",
                                             "newOrder": f"{BASE}/order"})
        if request.method == "HEAD":
            return self.reply(200)
        if self.bad_nonce_once:
            self.bad_nonce_once = False
            self.nonces.clear()
        protected, payload = self.check_jws(request)
        if protected is None:
            return self.reply(400, {"type": "urn:ietf:params:acme:error:badNonce"})
        if url == f"{BASE}/acct":
            assert payload == {"termsOfServiceAgreed": True}
            return self.reply(201, {"status": "valid"}, location=f"{BASE}/acct/1")
        if url == f"{BASE}/order":
            self.orders += 1
            assert payload == {"identifiers": [{"type": "dns", "value": HOST}]}
            return self.reply(201, {"status": "pending", "authorizations": [f"{BASE}/authz/1"],
                                    "finalize": f"{BASE}/finalize"}, location=f"{BASE}/order/1")
        if url == f"{BASE}/authz/1":
            assert payload is None
            return self.reply(200, {"status": self.state["challenge"], "challenges": [
                {"type": "http-01", "url": f"{BASE}/chall/x", "token": "no"},
                {"type": "dns-01", "url": f"{BASE}/chall/1", "token": self.token}]})
        if url == f"{BASE}/chall/1":
            assert payload == {}
            self.state["challenge"] = "valid"
            return self.reply(200, {"status": "processing"})
        if url == f"{BASE}/finalize":
            self.cert_pem = self.sign(unb64(payload["csr"]))
            self.state["order"] = "valid"
            return self.reply(200, {"status": "processing"})
        if url == f"{BASE}/order/1":
            body = {"status": "ready" if self.state["order"] == "pending" else "valid"}
            if body["status"] == "valid":
                body["certificate"] = f"{BASE}/cert/1"
            return self.reply(200, body)
        if url == f"{BASE}/cert/1":
            assert request.headers["accept"] == "application/pem-certificate-chain"
            return self.reply(200, self.cert_pem)
        raise AssertionError(url)


def make_client(ca, dns):
    http = httpx.AsyncClient(transport=httpx.MockTransport(ca.handler))

    async def no_sleep(_s):
        return None

    return acme.AcmeClient(directory_url=f"{BASE}/dir", account_key=acme.new_ec_key(), dns=dns,
                           http=http, sleep=no_sleep)


@pytest.mark.asyncio
async def test_the_full_dns01_flow_publishes_the_rfc_value_and_clears_it():
    ca, dns = FakeCa(), FakeDns()
    client = make_client(ca, dns)
    key = acme.new_ec_key()
    pem = await client.obtain(HOST, key)
    assert x509.load_pem_x509_certificate(pem.encode()).public_key().public_numbers() == key.public_key().public_numbers()
    assert dns.events == [("set", acme.txt_value(ca.token, ca.jwk)), ("clear", acme.txt_value(ca.token, ca.jwk))]
    assert not dns.live and len(dns.events[0][1]) == 43


@pytest.mark.asyncio
async def test_a_bad_nonce_is_retried_once():
    ca = FakeCa()
    ca.bad_nonce_once = True
    await make_client(ca, FakeDns()).obtain(HOST, acme.new_ec_key())


@pytest.mark.asyncio
async def test_the_txt_record_is_cleared_when_validation_fails():
    ca, dns = FakeCa(), FakeDns()
    client = make_client(ca, dns)
    original = ca.handler

    def failing(request):
        if str(request.url) == f"{BASE}/chall/1":
            raise httpx.ConnectError("boom")
        return original(request)

    client._http = httpx.AsyncClient(transport=httpx.MockTransport(failing))
    with pytest.raises(acme.AcmeError):
        await client.obtain(HOST, acme.new_ec_key())
    assert not dns.live and [e[0] for e in dns.events] == ["set", "clear"]


def test_the_txt_value_matches_the_rfc_construction():
    jwk = {"crv": "P-256", "kty": "EC", "x": "AAAA", "y": "BBBB"}
    import hashlib
    thumb = base64.urlsafe_b64encode(hashlib.sha256(
        b'{"crv":"P-256","kty":"EC","x":"AAAA","y":"BBBB"}').digest()).rstrip(b"=").decode()
    expected = base64.urlsafe_b64encode(hashlib.sha256(f"tok.{thumb}".encode()).digest()).rstrip(b"=").decode()
    assert acme.thumbprint(jwk) == thumb and acme.txt_value("tok", jwk) == expected


def manager(tmp_path, ca, dns, clock=None):
    async def obtain(hostname, key):
        client = make_client(ca, dns)
        client._key = m.load_or_create_key(m.account_key_path)
        client._jwk = acme.jwk_of(client._key)
        return await client.obtain(hostname, key)

    kwargs = {"clock": clock} if clock else {}
    m = certs.CertManager(directory=tmp_path / "pl", directory_url=f"{BASE}/dir", obtain=obtain, **kwargs)
    return m


@pytest.mark.asyncio
async def test_keys_are_private_the_cert_is_reused_and_renewed_in_place(tmp_path):
    ca, dns = FakeCa(days=90), FakeDns()
    m = manager(tmp_path, ca, dns)
    ctx = await m.ensure(HOST)
    assert isinstance(ctx, ssl.SSLContext) and ca.orders == 1
    assert stat.S_IMODE(os.stat(tmp_path / "pl").st_mode) == 0o700
    for path in (m.key_path, m.account_key_path, m.cert_path):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert await m.ensure(HOST) is ctx and ca.orders == 1
    m2 = manager(tmp_path, FakeCa(days=20), dns)
    assert m2.needs_renewal(HOST) is False
    later = datetime.now(timezone.utc) + timedelta(days=61)
    m3 = manager(tmp_path, ca, dns, clock=lambda: later)
    assert m3.needs_renewal(HOST) is True
    first = m.cert_path.read_bytes()
    await m.renew(HOST)
    assert m.cert_path.read_bytes() != first and ca.orders == 2
    assert await m.ensure(HOST) is ctx


@pytest.mark.asyncio
async def test_a_certificate_from_another_directory_or_name_is_not_reused(tmp_path):
    ca, dns = FakeCa(), FakeDns()
    await manager(tmp_path, ca, dns).ensure(HOST)
    other = certs.CertManager(directory=tmp_path / "pl", directory_url="https://prod.test/dir", obtain=None)
    assert other.needs_renewal(HOST) is True
    assert manager(tmp_path, ca, dns).needs_renewal("other." + HOST) is True
