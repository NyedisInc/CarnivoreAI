
import json
from unittest.mock import MagicMock

import pytest

from src.core.federation import bonjour, discovery

UUID = "11111111-2222-3333-4444-555555555555"


class FakeLib:

    def __init__(self):
        self.registers = []
        self.deallocs = 0

    def DNSServiceRegister(self, *a):
        self.registers.append(a)
        return 0

    def DNSServiceBrowse(self, *a):
        return 0

    def DNSServiceResolve(self, *a):
        return 0

    def DNSServiceGetAddrInfo(self, *a):
        return 0

    def DNSServiceRefSockFD(self, ref):
        return 99

    def DNSServiceProcessResult(self, ref):
        return 0

    def DNSServiceRefDeallocate(self, ref):
        self.deallocs += 1


@pytest.fixture
def lib():
    bonjour.reset_library()
    fake = FakeLib()
    yield fake
    bonjour.reset_library()


def make(tmp_path, lib, advertise=None):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({} if advertise is None else {"federation": {"advertise": advertise}}))
    d = discovery.Discovery(
        config_path=cfg, fid_provider=lambda: "FIDVALUE", platform_uuid_provider=lambda: UUID,
        name_provider=lambda: "Test-Mac", loader=lambda: lib,
    )
    d.start(MagicMock())
    return d


def test_txt_is_exactly_p_fid_mid_and_mid_is_hashed(tmp_path, lib):
    d = make(tmp_path, lib)
    assert d.state == discovery.STATE_ADVERTISING
    txt = lib.registers[0][9]
    record = bonjour.decode_txt(txt)
    assert set(record) == {"p", "fid", "mid"}
    assert record["p"] == "1" and record["fid"] == "FIDVALUE"
    assert record["mid"] == discovery.hash_machine_id(UUID)
    assert UUID not in txt.decode() and record["mid"] != UUID


def test_off_registers_nothing(tmp_path, lib):
    d = make(tmp_path, lib, advertise=False)
    assert lib.registers == [] and d.state == discovery.STATE_OFF


def test_toggle_off_withdraws_and_on_reregisters(tmp_path, lib):
    d = make(tmp_path, lib)
    d.set_advertise(False)
    assert lib.deallocs == 1 and d.state == discovery.STATE_OFF
    d.set_advertise(True)
    assert len(lib.registers) == 2


def test_missing_dns_sd_fails_soft(tmp_path):
    bonjour.reset_library()

    def boom():
        raise bonjour.BonjourUnavailableError("no dns_sd")

    d = discovery.Discovery(config_path=tmp_path / "c.json", loader=boom)
    d.start(MagicMock())
    assert d.state == discovery.STATE_UNAVAILABLE
    bonjour.reset_library()


def test_pin_and_identity_changed(tmp_path, lib):
    d = make(tmp_path, lib)
    discovery.write_pin(tmp_path / "config.json", "Peer", "AAA")
    d._peers["Peer"] = {"name": "Peer", "host": "Peer.local.", "port": 22,
                        "addresses": ["192.0.2.15"], "p": "1", "fid": "AAA", "mid": "m"}
    assert d.discovered(["acme@peer"])[0]["state"] == "pinned"
    assert d.discovered(["acme@peer"])[0]["known_host"] is True
    d._peers["Peer"]["fid"] = "BBB"
    assert d.discovered()[0]["state"] == "identity_changed"
    d._peers["Peer"]["name"] = "Other"
    assert d.discovered()[0]["state"] == "new"
