
from __future__ import annotations

import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
ENTRY = re.compile(r"'(?P<key>[A-Za-z0-9_.]+)'\s*:\s*'(?P<value>(?:[^'\\]|\\.)*)'")
OLD_NAME = re.compile(r"\b(packs?|alpha)\b", re.IGNORECASE)
ALLOWED = {"skill.browse.packs.heading"}
PACK_MEANS_MACHINES = ("pack.", "projects.page.pack", "projects.page.action.pack", "projects.page.tag.pack",
                       "gallery.preset.pack_", "ai.feature.pack_", "warez.kind.chip.loadout", "approvals.display.verb.pack",
                       "hosts.tab.pack", "opscenter.nav.hosts", "viz.pack", "first_run.", "computers.",
                       "app_alert.source.pack_skills", "app_alert.pack_skills.", "sidebar.pack.", "drawer.pack.",
                       "drawer.stats.pack", "session.send.none", "warez.skills.tab.pack", "skills.pack.",
                       "notify.type.pack.skills.", "notify.copy.pack.skills.", "menubar.setup.joined",
                       "roster.",
                       "skills.prov.consent_pack")
ALPHA_IS_THE_LEAD = ("pack.machines.", "pack.work.", "app_alert.pack_skills.", "drawer.pack.alpha", "skills.pack.",
                     "notify.type.pack.skills.")
ALPHA = re.compile(r"\balpha\b", re.IGNORECASE)


def test_no_catalog_value_names_the_feature_pack_or_alpha() -> None:
    entries = [(m["key"], m["value"]) for m in ENTRY.finditer(CATALOG.read_text())]
    assert len(entries) > 1000
    assert dict(entries)["cplug.huddle.swarm.rank.alpha"] == "SysOp"
    bad = [f"{k}: {v}" for k, v in entries if k not in ALLOWED and not k.startswith(ALPHA_IS_THE_LEAD)
           and (ALPHA if k.startswith(PACK_MEANS_MACHINES) else OLD_NAME).search(v)]
    assert bad == []


def test_ledger_total_label_no_longer_borrows_the_word_swarm() -> None:
    values = {m["key"]: m["value"] for m in ENTRY.finditer(CATALOG.read_text())}
    assert values["ledger.total.label"] == "all accounts total"
