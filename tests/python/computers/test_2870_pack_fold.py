
import json
from unittest.mock import MagicMock

from src.core.computers import join_job
from src.core.federation import bonjour, discovery

HOST, DOCK, STRANGER = "rbofuiAAAAAAAAAAAAAAAAAAAA", "nsml2sBBBBBBBBBBBBBBBBBBBB", "zzzzzzCCCCCCCCCCCCCCCCCCCC"


def disc(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    return discovery.Discovery(config_path=cfg)


def seen(d, name, fid, extra=()):
    d._on_resolve(0, name, name + ".local.", 22, bonjour.encode_txt([("p", "1"), ("fid", fid), ("mid", "m" + name), ("lp", "9443"), *extra]))


def test_pm_folds_members_and_stays_inside_the_txt_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(bonjour, "get_addr_info", lambda *a, **k: MagicMock(fd=5))
    members = [("nsml2sBBBB", "dock")] + [(f"{i:06d}XXXX", f"computer number {i}") for i in range(30)]
    pairs = discovery.build_txt_pairs(HOST, None, 9443, "id", "nostromo", members)
    assert discovery._txt_size(pairs) <= discovery.TXT_BUDGET and dict(pairs)["pm"].startswith("nsml2s:dock,")
    assert all(k != "pm" for k, _ in discovery.build_txt_pairs(HOST, None, 9443, "id", "nostromo"))
    d = disc(tmp_path)
    seen(d, "Nostromo", HOST, [("pn", "id"), ("lb", "nostromo"), ("pm", "nsml2s:dock")])
    seen(d, "Adams-Mac-mini", DOCK)
    seen(d, "Stranger", STRANGER)
    rows = d.candidates()
    assert [r["name"] for r in rows] == ["Nostromo", "Stranger"]
    assert rows[0]["members"] == [{"label": "dock", "fid_short": "nsml2s", "seen": True}]
    assert join_job._candidate(rows[0])["label"] == "id" and join_job._candidate(rows[0])["members"][0]["label"] == "dock"


def test_a_main_without_pm_leaves_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(bonjour, "get_addr_info", lambda *a, **k: MagicMock(fd=5))
    d = disc(tmp_path)
    seen(d, "Nostromo", HOST, [("pn", "id")])
    seen(d, "Adams-Mac-mini", DOCK)
    assert [r["name"] for r in d.candidates()] == ["Adams-Mac-mini", "Nostromo"]
