
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.argent import cost_poller, health, refresh, work_items
from src.core.argent.client import ArgentClient, Unreachable
from src.core.argent.delegate import Delegates
from src.core.argent.refresh import Refresher
from src.core.argent.settings import ArgentSettings

SERVER, GATEWAY, CA = "https://cp.argent.test", "https://gw.argent.test", "/gateway-ca.pem"


class Recorder(ArgentClient):

    seen: List[tuple] = []

    def __init__(self, base_url: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(base_url, *args, **kwargs)
        Recorder.seen.append((base_url, self._ca_path))

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        raise Unreachable("recorded")


@pytest.fixture(autouse=True)
def recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    Recorder.seen = []
    for module in (work_items, cost_poller, refresh, health):
        monkeypatch.setattr(module, "ArgentClient", Recorder)
    monkeypatch.setattr("src.core.argent.delegate.ArgentClient", Recorder)


def test_control_plane_clients_skip_the_gateway_ca_and_the_gateway_probe_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ArgentSettings(server_url=SERVER, gateway_url=GATEWAY, ca_path=CA)
    monkeypatch.setattr(work_items.settings_module, "read", lambda path=None: cfg)
    monkeypatch.setattr(work_items, "_tenant_and_token", lambda: ("ten_1", "tok"))
    monkeypatch.setattr(work_items, "get_runtime", lambda: SimpleNamespace(store=SimpleNamespace(mark_login_expired=lambda: None)))
    work_items._pull.client, work_items._pull.client_key = None, ""
    asyncio.run(work_items.client_for_call())
    monkeypatch.setattr(cost_poller, "get_runtime", lambda: SimpleNamespace(store=SimpleNamespace(mark_login_expired=lambda: None)))
    cost_poller._client(SERVER, "tok")
    login = {"tenant_id": "ten_1", "identity_id": "idn_1", "display_name": "o", "expires_at": 4e9}
    store = SimpleNamespace(get_login=lambda: login, get_login_issued_at=lambda: 0.0, login_issued_at=lambda: 0.0,
                            login_source_recorded=lambda: "own", login_expired=lambda: False)
    tokens = SimpleNamespace(read=lambda tenant: "tok")
    asyncio.run(Refresher(store, tokens, read_settings=lambda: cfg, clock=lambda: 1.0)._attempt())
    asyncio.run(Delegates(store, tokens, read_settings=lambda: cfg)._client())
    assert [url for url, _ in Recorder.seen] == [SERVER] * 4
    assert all(ca == "" for _, ca in Recorder.seen), Recorder.seen
    Recorder.seen = []
    asyncio.run(health.probe(GATEWAY, SERVER, ca_path=CA))
    assert (GATEWAY, CA) in Recorder.seen and (SERVER, "") in Recorder.seen


def test_gateway_context_trusts_public_roots_plus_the_argent_ca(tmp_path: Any) -> None:
    import datetime
    import ssl

    import certifi
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "argent test ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    public = ssl.create_default_context(cafile=certifi.where()).cert_store_stats()["x509_ca"]
    context = ArgentClient("https://x.invalid", ca_path=str(ca))._verify()
    assert context.cert_store_stats()["x509_ca"] == public + 1
