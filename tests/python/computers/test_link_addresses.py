
import socket

import pytest

from src.core.computers import link_addresses

IFCONFIG = "lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\nen0: flags\n\tinet 10.0.0.5 netmask 0xffffff00\n\tinet 169.254.1.2 netmask 0xffff0000\n\tinet 100.64.0.9 netmask 0xff\n"
IP_O = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
    "2: eth0    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\\       valid_lft forever\n"
    "3: tailscale0    inet 100.101.102.103/32 scope global tailscale0\\       valid_lft forever\n"
    "4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever\n"
    "5: wlan0    inet 169.254.9.9/16 scope link wlan0\\       valid_lft forever\n"
)


def _oserror(*_a, **_k):
    raise OSError("no route")


def _fake_run(ifconfig="", ip=None, name="air"):
    def run(argv):
        if "scutil" in argv[0]:
            return name
        if "ifconfig" in argv[0]:
            return ifconfig
        return ip.get(argv[0], "") if ip else ""
    return run


@pytest.mark.parametrize(
    "platform, run, default, getaddr, expected",
    [
        ("darwin", _fake_run(ifconfig=IFCONFIG), None, None, ["air.local", "100.64.0.9", "10.0.0.5"]),
        ("darwin", _fake_run(ifconfig=IFCONFIG), "10.0.0.5", None, ["air.local", "10.0.0.5", "100.64.0.9"]),
        ("linux", _fake_run(ip={"/usr/sbin/ip": IP_O}), "192.168.1.20", None, ["192.168.1.20", "100.101.102.103", "172.17.0.1"]),
        ("linux", _fake_run(ip={"/bin/ip": IP_O}), None, None, ["100.101.102.103", "192.168.1.20", "172.17.0.1"]),
        ("linux", _fake_run(), "192.168.1.20", None, ["192.168.1.20"]),
        ("win32", _fake_run(), "192.168.1.20", ["10.1.1.1", "192.168.1.20", "127.0.0.1"], ["192.168.1.20", "10.1.1.1"]),
        ("win32", _fake_run(), None, OSError, []),
        ("linux", _fake_run(ip={"/sbin/ip": "".join(f"{i}: e{i} inet 10.0.0.{i + 1}/24 scope global\\\n" for i in range(9))}), "10.0.0.9",
         None, ["10.0.0.9", "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5"]),
    ],
)
def test_local_addresses(monkeypatch, platform, run, default, getaddr, expected):
    monkeypatch.setattr(link_addresses, "_platform", lambda: platform)
    monkeypatch.setattr(link_addresses, "_run", run)
    monkeypatch.setattr(link_addresses, "_default_route_address", lambda: default)
    if getaddr is OSError:
        monkeypatch.setattr(socket, "getaddrinfo", _oserror)
    elif getaddr is not None:
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", (h, 0)) for h in getaddr])
    monkeypatch.setattr(socket, "gethostname", lambda: "air.local")
    assert link_addresses.local_addresses() == expected


def test_default_route_address_is_none_on_oserror(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("network unreachable")
    monkeypatch.setattr(socket.socket, "connect", boom)
    assert link_addresses._default_route_address() is None
