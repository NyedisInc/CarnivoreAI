
import asyncio
import hashlib
import ssl
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.core.phone_link import acme, certs
from src.core.phone_link.custom_domain import challenge, hello
from tests.phone_link.test_acme import BASE, FakeCa, unb64

DOMAIN = "sync.example.com"


def client_hello_bytes(server_name, alpn):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    if alpn:
        ctx.set_alpn_protocols(alpn)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(incoming, outgoing, server_hostname=server_name)
    with pytest.raises(ssl.SSLWantReadError):
        obj.do_handshake()
    return outgoing.read()


def test_the_challenge_cert_carries_the_critical_acme_identifier_over_the_digest():
    digest = hashlib.sha256(b"token.thumb").digest()
    cert, _key = challenge.challenge_cert(DOMAIN, digest)
    ext = cert.extensions.get_extension_for_oid(challenge.ACME_IDENTIFIER_OID)
    assert ext.critical is True
    assert ext.value.value == b"\x04\x20" + digest
    assert cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
        x509.DNSName) == [DOMAIN]
    with pytest.raises(ValueError):
        challenge.challenge_cert(DOMAIN, b"short")


def test_client_hello_parsing_reads_sni_and_alpn_and_asks_for_more_bytes():
    raw = client_hello_bytes(DOMAIN, ["acme-tls/1"])
    parsed = hello.parse(raw)
    assert parsed.sni == DOMAIN and parsed.alpn == ["acme-tls/1"] and parsed.is_acme_challenge
    assert hello.parse(raw[:10]) is None and hello.parse(raw[:-1]) is None
    both = hello.parse(client_hello_bytes(DOMAIN, ["acme-tls/1", "http/1.1"]))
    assert not both.is_acme_challenge
    assert hello.parse(client_hello_bytes(DOMAIN, None)).alpn == []
    with pytest.raises(hello.HelloError):
        hello.parse(b"GET / HTTP/1.1\r\n\r\n")


@pytest.mark.asyncio
async def test_the_responder_presents_the_validation_cert_only_for_acme_tls_1():
    responder = challenge.ChallengeResponder()
    await responder.start()
    digest = hashlib.sha256(b"k").digest()
    try:
        assert not responder.has_open
        await responder.publish(DOMAIN, digest)
        assert responder.has_open
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        ctx.set_alpn_protocols(["acme-tls/1"])
        reader, writer = await asyncio.open_connection("127.0.0.1", responder.port, ssl=ctx, server_hostname=DOMAIN)
        assert writer.get_extra_info("ssl_object").selected_alpn_protocol() == "acme-tls/1"
        cert = x509.load_der_x509_certificate(writer.get_extra_info("ssl_object").getpeercert(binary_form=True))
        assert cert.extensions.get_extension_for_oid(challenge.ACME_IDENTIFIER_OID).value.value == b"\x04\x20" + digest
        writer.close()
        plain = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        plain.check_hostname, plain.verify_mode = False, ssl.CERT_NONE
        plain.set_alpn_protocols(["http/1.1"])
        r, w = await asyncio.open_connection("127.0.0.1", responder.port, ssl=plain, server_hostname=DOMAIN)
        assert w.get_extra_info("ssl_object").selected_alpn_protocol() is None
        assert await asyncio.wait_for(r.read(10), 2) == b""
        w.close()
        await responder.clear(DOMAIN)
        assert not responder.has_open
    finally:
        await responder.stop()


def self_signed(name, tmp_path, stem):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=5))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / f"{stem}.pem", tmp_path / f"{stem}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path), cert.public_bytes(serialization.Encoding.DER)


async def served_cn(port, server_name):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ctx, server_hostname=server_name)
    der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    writer.close()
    return x509.load_der_x509_certificate(der).subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


@pytest.mark.asyncio
async def test_sni_selects_the_custom_certificate_only_for_the_custom_name(tmp_path):
    link_ctx, custom_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER), ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    link_ctx.load_cert_chain(*self_signed("dev.link.carnivore.ai", tmp_path, "link")[:2])
    custom_ctx.load_cert_chain(*self_signed(DOMAIN, tmp_path, "custom")[:2])
    ready = {"on": False}
    certs.install_sni_selector(link_ctx, lambda: (DOMAIN, custom_ctx) if ready["on"] else None)

    async def serve(reader, writer):
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=link_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await served_cn(port, DOMAIN) == "dev.link.carnivore.ai"
        ready["on"] = True
        assert await served_cn(port, DOMAIN) == DOMAIN
        assert await served_cn(port, DOMAIN.upper()) == DOMAIN
        assert await served_cn(port, "dev.link.carnivore.ai") == "dev.link.carnivore.ai"
        assert await served_cn(port, "other.example.com") == "dev.link.carnivore.ai"
    finally:
        server.close()
        await server.wait_closed()


class AlpnCa(FakeCa):

    def __init__(self, profiles=True):
        super().__init__(days=7)
        self.profiles, self.order_payload, self.validated = profiles, None, None

    def sign(self, csr_der):
        csr = x509.load_der_x509_csr(csr_der)
        now = datetime.now(timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake ca")])
        return (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(name).public_key(csr.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=6))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(DOMAIN)]), critical=False)
                .sign(self.ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())

    def handler(self, request):
        import json
        url = str(request.url)
        if request.method == "GET":
            meta = {"meta": {"profiles": {"shortlived": "160 hours"}}} if self.profiles else {}
            return httpx.Response(200, json={"newNonce": f"{BASE}/nonce", "newAccount": f"{BASE}/acct",
                                             "newOrder": f"{BASE}/order", **meta})
        if url == f"{BASE}/order":
            protected, payload = self.check_jws(request)
            self.order_payload = payload
            return self.reply(201, {"status": "pending", "authorizations": [f"{BASE}/authz/1"],
                                    "finalize": f"{BASE}/finalize"}, location=f"{BASE}/order/1")
        if url == f"{BASE}/authz/1":
            self.check_jws(request)
            return self.reply(200, {"status": self.state["challenge"], "identifier": {"type": "dns", "value": DOMAIN},
                                    "challenges": [{"type": "dns-01", "url": f"{BASE}/chall/d", "token": "no"},
                                                   {"type": "tls-alpn-01", "url": f"{BASE}/chall/1", "token": self.token}]})
        if url == f"{BASE}/chall/1":
            self.validated = list(self.alpn.open)
            return super().handler(request)
        return super().handler(request)


class FakeAlpn:

    def __init__(self):
        self.events, self.open = [], {}

    async def publish(self, domain, digest):
        self.events.append(("publish", domain, digest))
        self.open[domain] = digest

    async def clear(self, domain):
        self.events.append(("clear", domain))
        self.open.pop(domain, None)


def alpn_client(ca, alpn, profile=acme.SHORTLIVED):
    ca.alpn = alpn
    http = httpx.AsyncClient(transport=httpx.MockTransport(ca.handler))

    async def no_sleep(_s):
        return None

    return acme.AcmeClient(directory_url=f"{BASE}/dir", account_key=acme.new_ec_key(), alpn=alpn,
                           profile=profile, http=http, sleep=no_sleep)


@pytest.mark.asyncio
async def test_tls_alpn_01_orders_the_shortlived_profile_and_hands_over_the_key_authorization_digest():
    ca, alpn = AlpnCa(), FakeAlpn()
    client = alpn_client(ca, alpn)
    key = acme.new_ec_key()
    pem = await client.obtain(DOMAIN, key)
    assert x509.load_pem_x509_certificate(pem.encode()).subject is not None
    assert ca.order_payload == {"identifiers": [{"type": "dns", "value": DOMAIN}], "profile": "shortlived"}
    expected = hashlib.sha256(f"{ca.token}.{acme.thumbprint(ca.jwk)}".encode()).digest()
    assert alpn.events == [("publish", DOMAIN, expected), ("clear", DOMAIN)]
    assert ca.validated == [DOMAIN]


@pytest.mark.asyncio
async def test_an_order_is_refused_locally_when_the_ca_lacks_the_shortlived_profile():
    ca, alpn = AlpnCa(profiles=False), FakeAlpn()
    with pytest.raises(acme.AcmeError, match="shortlived"):
        await alpn_client(ca, alpn).obtain(DOMAIN, acme.new_ec_key())
    assert ca.order_payload is None and alpn.events == []


@pytest.mark.asyncio
async def test_the_challenge_is_cleared_when_validation_fails():
    ca, alpn = AlpnCa(), FakeAlpn()
    client = alpn_client(ca, alpn)
    original = ca.handler

    def failing(request):
        if str(request.url) == f"{BASE}/chall/1":
            raise httpx.ConnectError("boom")
        return original(request)

    client._http = httpx.AsyncClient(transport=httpx.MockTransport(failing))
    with pytest.raises(acme.AcmeError):
        await client.obtain(DOMAIN, acme.new_ec_key())
    assert [e[0] for e in alpn.events] == ["publish", "clear"] and not alpn.open


@pytest.mark.asyncio
async def test_account_uri_is_the_location_new_account_answers():
    ca = AlpnCa()
    assert await alpn_client(ca, FakeAlpn()).account_uri() == f"{BASE}/acct/1"


def test_a_client_needs_exactly_one_challenge_kind():
    with pytest.raises(ValueError):
        acme.AcmeClient(directory_url=f"{BASE}/dir", account_key=acme.new_ec_key())
