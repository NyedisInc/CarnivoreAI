
import json
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.core.phone_link.certs import describe_cert


def _store(directory, directory_url):
    key = ec.generate_private_key(ec.SECP256R1())
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "(STAGING) Test Intermediate")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "h")]))
            .issuer_name(issuer).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + timedelta(days=90)).sign(key, hashes.SHA256()))
    (directory / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "cert.json").write_text(json.dumps({"hostname": "h", "directory": directory_url}))


def test_describe_cert_names_issuer_expiry_and_environment(tmp_path):
    _store(tmp_path, "https://acme-staging-v02.api.letsencrypt.org/directory")
    info = describe_cert(tmp_path)
    assert info["issuer"] == "(STAGING) Test Intermediate" and info["environment"] == "staging"
    assert datetime.fromisoformat(info["not_after"]) > datetime.now(timezone.utc) + timedelta(days=80)
    _store(tmp_path, "https://acme-v02.api.letsencrypt.org/directory")
    assert describe_cert(tmp_path)["environment"] == "production"


def test_describe_cert_is_none_without_a_certificate(tmp_path):
    assert describe_cert(tmp_path) is None
    (tmp_path / "cert.pem").write_text("not a certificate")
    assert describe_cert(tmp_path) is None
