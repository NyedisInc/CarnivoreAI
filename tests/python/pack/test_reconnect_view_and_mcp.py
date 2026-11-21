
from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from src.core.mcp import pack_machines_tools  # noqa: E402
from src.core.mcp.pack_machines_tools import SPECS  # noqa: E402
from src.core.pack.machines import capabilities as caps, reconnect_view, roster_doc  # noqa: E402
from src.core.pack.machines.interim_policy import HomeState  # noqa: E402

KEY = base64.urlsafe_b64encode(bytes(32)).decode().rstrip("=")
CERT = base64.b64encode(b"der").decode()


def _roster(eligible=("b",), home="a"):
    return roster_doc.Roster(generation=4, alpha="a", home=home, issued_at=100, computers=[
        roster_doc.RosterComputer(install_id=i, fed_public_key=KEY, cert=CERT, takeover_eligible=i in eligible) for i in "abc"])


def _view(master="a", states=("connected", "connected", "disconnected"), roster_caps=(True, True, False)):
    rows = [{"install_id": i, "is_self": i == "a", "state": "self" if i == "a" else s,
             "capabilities": [caps.CAP_ROSTER] if has else []} for i, s, has in zip("abc", states, roster_caps)]
    return {"master_install_id": master, "machines": rows}


def _aug(view, roster, *, home=HomeState(), relayed=(), takeover_on=True, known=lambda i: i == "b"):
    return reconnect_view.augment(view, roster=roster, home_state=home, relayed=set(relayed), relay_known=known, relay_on=True, takeover_on=takeover_on)


def test_view_fields_and_the_off_only_mcp_surface():
    assert _aug(_view(), _roster(), takeover_on=False)["takeover_available"] == {"ok": False, "reason": "off"}
    assert _aug(_view(), None)["takeover_available"]["reason"] == "alpha_not_updated"
    assert _aug(_view(roster_caps=(False, True, True)), _roster())["takeover_available"]["reason"] == "alpha_not_updated"
    assert _aug(_view(), _roster(eligible=(), home="a"))["takeover_available"]["reason"] == "no_eligible"
    assert _aug(_view(), _roster(eligible=("b",)))["takeover_available"] == {"ok": True, "reason": "ok"}
    two = _aug({"master_install_id": "a", "machines": _view()["machines"][:2]}, roster_doc.Roster(
        generation=1, alpha="a", home="a", issued_at=1, computers=_roster().computers[:2]))
    assert two["takeover_available"]["ok"] is True

    v = _aug(_view(states=("connected", "connected", "connected"), roster_caps=(True, True, False)), _roster(eligible=("b", "c")), relayed={"b"})
    by = {m["install_id"]: m for m in v["machines"]}
    assert (by["a"]["link_path"], by["b"]["link_path"], by["c"]["link_path"]) == (None, "relay", "direct")
    assert by["b"]["can_claim"] is True and by["c"]["can_claim"] is False and by["c"]["roster_v1"] is False
    assert (by["a"]["rank"], by["c"]["rank"], by["b"]["relay_id_known"], by["c"]["relay_id_known"]) == (0, 2, True, False)
    assert _aug(_view(states=("connected", "disconnected", "connected")), _roster())["machines"][1]["link_path"] == "none"
    assert (v["generation"], v["roster_issued_at"], v["home_install_id"], v["interim"]) == (4, 100, "a", False)

    assert _aug(_view(master="b"), _roster())["interim"] is True
    assert _aug(_view(master="b"), _roster(), home=HomeState(home_override="b"))["interim"] is False
    assert _aug(_view(master="b"), None)["interim"] is False

    sent = []
    spec = next(s for s in SPECS if s.name == "pack_reconnect_off")
    assert spec.properties == {} and spec.required == ()
    pack_machines_tools._reconnect_off(SimpleNamespace(route=lambda body, request: sent.append(body.model_dump()), request=None, args={}))
    assert sent == [{"relay": False, "takeover": False}]
    names = {s.name for s in SPECS}
    assert not {n for n in names if "reconnect" in n or "interim" in n} - {"pack_reconnect_off"}
    assert not {n for n in names if n.endswith("_on") and "reconnect" in n}
