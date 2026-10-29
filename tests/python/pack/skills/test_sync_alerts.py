
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from src.core.app_alerts import service  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.pack.machines import exchange, settings_doc  # noqa: E402
from src.core.pack.skills import alerts, apply as ap, owner  # noqa: E402
from src.core.pack.skills.bundle import build_bundle, read_bundle  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState  # noqa: E402
from src.core.pack.machines.settings_custody import SettingsCustody  # noqa: E402
from src.core.pack.skills.scan import scan_root  # noqa: E402
from src.core.pack.skills.targets import receiver_roots  # noqa: E402

LABELS = {"A": "nostromo", "B": "studio", "C": "newt", "X": "ripley"}


class Rt:

    def __init__(self, doc: settings_doc.PackSettings) -> None:
        self.doc = doc
        self.state = SimpleNamespace(save_settings=self.save, stored_settings=lambda: self.doc)
        self.custody = SettingsCustody(install_id="ME", state=self.state, default_master=lambda: "A")
        self.install_id = "ME"
        self.skills_settings_changed = lambda source, sender: None

    def save(self, doc: settings_doc.PackSettings, signature=None, signed_mode: bool = False, anchor=None) -> None:
        self.doc = doc

    def settings(self) -> settings_doc.PackSettings:
        return self.doc

    def _notify(self, *args) -> None:
        pass


def remote(master: str, counter: int, setter: str) -> dict:
    return settings_doc.PackSettings(master_install_id=master, rev=(counter, setter)).model_dump(mode="json")


def rows(prefix: str) -> list[dict]:
    found = service.list_view(Path(service._db_path), include_closed=True, limit=200)["alerts"]
    return sorted((r for r in found if r["key"].startswith(prefix)), key=lambda r: r["id"])


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    service.configure(db_path_for(state_dir), None)
    live: set[str] = {"X"}
    rt = Rt(settings_doc.default_doc("A"))
    alerts.configure(alerts.Seams("ME", lambda: (rt.doc.master_install_id, rt.doc.rev[1], rt.doc.rev[0]), lambda i: LABELS.get(i, ""),
                                  lambda i: i in live))
    monkeypatch.setattr(exchange.direction, "contained", lambda _peer: False)
    yield SimpleNamespace(tmp=tmp_path, state=ReceiverState(tmp_path / "skills-state.json"), live=live, rt=rt)
    alerts.configure(None)
    service.configure(None, None)


def alpha_bundle(tmp: Path, text: str = "alpha copy\n"):
    src = tmp / "alpha" / ".claude" / "skills"
    (src / "demo").mkdir(parents=True, exist_ok=True)
    (src / "demo" / "SKILL.md").write_text(text)
    skill = scan_root(src, "claude").skills["demo"]
    build_bundle(tmp / "b.tgz", [("claude", "demo", src / "demo", skill.files)])
    doc = {"alpha": "X", "gen": 1, "skills": [["claude", "demo", skill.digest]], "removals": [], "unsynced": [], "choices": {}}
    return doc, read_bundle(tmp / "b.tgz", tmp / f"stage{len(list(tmp.glob('stage*')))}")


def receiver_home(tmp: Path):
    home = tmp / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    (home / ".carnivore" / "accounts").mkdir(parents=True)
    return home, receiver_roots(home, home / ".carnivore" / "accounts", [])


def test_alpha_changed_raises_once_per_computer_and_never_for_our_own_edit(world) -> None:
    rt, state = world.rt, world.state
    rt.skills_settings_changed = lambda source, sender: alerts.check_alpha(state, source, sender)
    alerts.check_alpha(state, "check")
    alerts.check_placers(state)
    assert rows("pack_skills.") == []
    assert exchange.PackMachines._merge_remote(rt, remote("B", 3, "ME"), "B") is True
    (row,) = rows(alerts.ALPHA_KEY)
    assert row["params"] == {"new": "studio", "old": "nostromo", "claimed": "this computer", "sender": "studio"}
    again = next(a for a in row["actions"] if a["id"] == "make_alpha_again")
    assert (again["method"], again["route"], again["body"]) == ("PUT", "/pack/master", {"machine": "A"})
    assert exchange.PackMachines._merge_remote(rt, remote("B", 3, "ME"), "B") is False
    alerts.check_alpha(ReceiverState(state.path), "check")
    assert [(r["id"], r["count"]) for r in rows(alerts.ALPHA_KEY)] == [(row["id"], 1)]
    assert exchange.PackMachines._merge_remote(rt, remote("C", 4, "B"), "B") is True
    (row2,) = rows(alerts.ALPHA_KEY)
    assert (row2["id"], row2["count"], row2["params"]["new"], row2["params"]["old"]) == (row["id"], 2, "newt", "studio")
    rt.doc = settings_doc.edited(rt.doc, {"master_install_id": "A"}, "ME")
    alerts.check_alpha(state, "local_edit")
    assert [(r["id"], r["count"]) for r in rows(alerts.ALPHA_KEY)] == [(row["id"], 2)]
    rt.doc = settings_doc.default_doc("B")
    alerts.check_alpha(state, "check")
    (row3,) = rows(alerts.ALPHA_KEY)
    assert (row3["count"], row3["params"]["claimed"], row3["params"]["sender"]) == (3, "pairing", "this computer")
    service.dismiss(Path(service._db_path), row3["id"])
    rt.doc = settings_doc.default_doc("A")
    alerts.check_alpha(state, "check")
    assert len(rows(alerts.ALPHA_KEY)) == 2


def test_a_replaced_local_edit_raises_once_and_names_the_trash_folder(world) -> None:
    home, roots = receiver_home(world.tmp)
    (home / ".claude" / "skills" / "demo").mkdir()
    (home / ".claude" / "skills" / "demo" / "SKILL.md").write_text("the receiver's own edit\n")
    doc, bundle = alpha_bundle(world.tmp)
    ap.apply_document(doc, bundle, roots, world.state)
    (row,) = rows(alerts.EDIT_PREFIX)
    assert row["params"]["name"] == "demo" and row["params"]["alpha"] == "ripley" and row["severity"] == "info"
    assert Path(row["params"]["folder"]).name == ".carnivore-trash" and any(Path(row["params"]["folder"]).glob("demo-*"))
    ap.apply_document(doc, bundle, roots, world.state)
    assert len(rows(alerts.EDIT_PREFIX)) == 1
    alerts.replaced([("claude", f"s{i}", f"/t/s{i}-1") for i in range(4)], "X", 9)
    (summary,) = rows(alerts.EDITS_PREFIX)
    assert summary["params"]["count"] == 4


def test_placed_skills_alert_survives_a_dismissal_and_trash_placed_resolves_it(world) -> None:
    home, roots = receiver_home(world.tmp)
    doc, bundle = alpha_bundle(world.tmp)
    ap.apply_document(doc, bundle, roots, world.state)
    alerts.check_placers(world.state)
    assert rows(alerts.PLACER_PREFIX) == []
    world.live.clear()
    for _ in range(3):
        alerts.check_placers(world.state)
    (row,) = rows(alerts.PLACER_PREFIX)
    assert row["params"] == {"label": "ripley", "count": 1}
    remove = next(a for a in row["actions"] if a["id"] == "remove_placed")
    inner = remove["actions"][0]
    assert (inner["route"], inner["body"], inner["tone"]) == ("/pack/skills/trash-placed", {"from_install_id": "X"}, "danger")
    service.dismiss(Path(service._db_path), row["id"])
    world.live.add("X")
    alerts.check_placers(world.state)
    world.live.clear()
    alerts.check_placers(world.state)
    states = [r["state"] for r in rows(alerts.PLACER_PREFIX)]
    assert len(states) == 2 and states[1] == "active"
    assert owner.trash_placed(world.state, "X", roots) == [("claude", "demo")]
    alerts.check_placers(world.state)
    assert rows(alerts.PLACER_PREFIX)[-1]["state"] == "resolved"
    doc2, bundle2 = alpha_bundle(world.tmp, "alpha copy 2\n")
    ap.apply_document({**doc2, "gen": 2}, bundle2, roots, world.state)
    alerts.check_placers(world.state)
    view = owner.receiver_view(SimpleNamespace(state=world.state), "B", "studio")
    assert view["rows"][0]["placed_by"] == {"id": "X", "label": "ripley"}


def test_nothing_crashes_or_raises_without_state_or_a_configured_service(world, tmp_path) -> None:
    fresh = ReceiverState(tmp_path / "none" / "state.json")
    alerts.check_alpha(fresh, "check")
    alerts.check_placers(fresh)
    assert rows("pack_skills.") == []
    alerts.check_alpha(world.state, "check")
    service.configure(None, None)
    world.rt.doc = settings_doc.default_doc("B")
    alerts.check_alpha(world.state, "check")
    assert world.state.load()["alerted"]["alpha_seen"] == "A"
    alerts.replaced([("claude", "demo", "/t/demo-1")], "X", 1)
    world.live.clear()
    alerts.check_placers(world.state)
