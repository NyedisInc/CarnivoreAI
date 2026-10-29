
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from src.core.federation import bonjour, discovery
from tests.python.federation.test_discovery import UUID, FakeLib


@pytest.fixture
def lib():
    bonjour.reset_library()
    yield FakeLib()
    bonjour.reset_library()


def make(tmp_path, lib, port):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    state = {"port": port}
    d = discovery.Discovery(
        config_path=cfg, fid_provider=lambda: "FIDVALUE", platform_uuid_provider=lambda: UUID,
        name_provider=lambda: "Test-Mac", loader=lambda: lib,
        link_port_provider=lambda: state["port"],
    )
    d.start(MagicMock())
    return d, state


def txt_of(lib, i=-1):
    return bonjour.decode_txt(lib.registers[i][9])


def test_lp_emitted_only_with_a_port_and_follows_changes(tmp_path, lib):
    d, state = make(tmp_path, lib, None)
    assert "lp" not in txt_of(lib)
    state["port"] = 9443
    d.refresh_link_port()
    assert txt_of(lib)["lp"] == "9443" and len(lib.registers) == 2
    state["port"] = None
    d.refresh_link_port()
    assert "lp" not in txt_of(lib)
    assert discovery.build_txt_pairs("f", None, 65535) == discovery.build_txt_pairs("f", None)


@pytest.mark.parametrize("raw,want", [("9443", 9443), ("0", None), ("65536", None), ("x1", None),
                                      ("", None), ("0x10", None), ("65535", 65535)])
def test_parse_link_port(raw, want):
    assert discovery.parse_link_port(raw) == want


def resolve(d, name, fid, lp, addrs):
    txt = bonjour.encode_txt([("p", "1"), ("fid", fid), ("mid", "m" + name)] + ([("lp", lp)] if lp else []))
    d._on_resolve(0, name, name + ".local.", 22, txt)
    d._peers[name]["addresses"] = list(addrs)


def test_candidates_need_lp_carry_fid_short_and_exclude_self(tmp_path, lib, monkeypatch):
    d, _ = make(tmp_path, lib, None)
    monkeypatch.setattr(bonjour, "get_addr_info", lambda *a, **k: MagicMock(fd=5))
    resolve(d, "alpha", "abcdef123456", "9443", ["192.0.2.13"])
    resolve(d, "beta", "ffffff", "", ["192.0.2.17"])
    resolve(d, "gamma", "123456789", "bad", ["198.51.100.13"])
    d._on_resolve(0, "me", "me.local.", 22,
                  bonjour.encode_txt([("p", "1"), ("fid", "x"), ("mid", discovery.hash_machine_id(UUID)),
                                      ("lp", "9443")]))
    assert d.candidates() == [{"name": "alpha", "fid": "abcdef123456", "fid_short": "abcdef",
                               "addresses": ["192.0.2.13"], "lp": 9443, "pack_name": None}]


def test_probe_picks_only_the_one_with_its_join_port_open():
    async def run():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        join_port = server.sockets[0].getsockname()[1]
        cands = [{"name": "open", "addresses": ["127.0.0.1"], "lp": join_port - 1},
                 {"name": "shut", "addresses": ["127.0.0.1"], "lp": 1},
                 {"name": "edge", "addresses": ["127.0.0.1"], "lp": 65535}]
        try:
            return await discovery.probe_join_ports(cands, timeout=1.0), join_port
        finally:
            server.close()

    found, _ = asyncio.run(run())
    assert [c["name"] for c in found] == ["open"] and found[0]["join_address"] == "127.0.0.1"


def test_test_slot_never_registers_on_bonjour(tmp_path, lib):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    d = discovery.Discovery(
        config_path=cfg, fid_provider=lambda: "FIDVALUE", platform_uuid_provider=lambda: UUID,
        name_provider=lambda: "Test-Mac", loader=lambda: lib, link_port_provider=lambda: 9443,
        advertise_allowed=False,
    )
    d.start(MagicMock())
    d.set_advertise(True)
    d.refresh_link_port()
    d.refresh_fid("F2")
    assert lib.registers == [] and d.state == discovery.STATE_OFF
