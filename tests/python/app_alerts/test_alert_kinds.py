
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from src.core.app_alerts import kinds, recheck
from src.core.app_alerts.store import AlertInputError, validate_action

ROOT = Path(__file__).resolve().parents[3]
CATALOG = (ROOT / "client/js/i18n/catalog.en.js").read_text()
CATALOG_KEYS = set(re.findall(r"^\s*'(app_alert\.[^']+)':", CATALOG, re.M))
TITLES = sorted(k for k in CATALOG_KEYS if k.endswith(".title") and k != "app_alert.panel.title")


def _key_for(title: str) -> str:
    return title[len("app_alert."):-len(".title")]


def _walk(actions: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    for action in actions:
        yield action
        yield from _walk(action.get("actions", []))


def _described(title: str, key: str = "", params: Dict[str, Any] | None = None, stored: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    return kinds.describe(7, key or _key_for(title), "backup_health", "warn", title, params or {}, stored or [], None)


@pytest.mark.parametrize("title", TITLES)
def test_every_alert_title_is_declared_so_none_ships_with_only_snooze_and_dismiss(title: str) -> None:
    declared = kinds.declared_for(_key_for(title), title)
    assert declared is not None, f"{title} has no entry in app_alerts/kinds.py"
    assert declared.kind in kinds.KINDS


def test_an_alert_with_no_fix_says_so_in_its_body() -> None:
    for title in TITLES:
        declared = kinds.declared_for(_key_for(title), title)
        if declared is None or declared.actions:
            continue
        stored_by_producer = title.startswith(("app_alert.automation.", "app_alert.pipeline.", "app_alert.pack_skills."))
        if not stored_by_producer:
            assert declared.default_detail_key in CATALOG_KEYS, f"{title}: no action and no explaining body"


def test_stale_and_unplugged_backups_offer_recheck_then_open_backups() -> None:
    for title in ("usb_stale", "usb_missing"):
        out = _described(f"app_alert.backup_health.{title}.title", "backup_health.usb_backup")
        assert [a["id"] for a in out["actions"]] == ["recheck", "open_backups"]


def test_a_producers_own_action_stays_first() -> None:
    own = {"id": "own", "label_key": "app_alert.x.own", "method": "POST", "route": "/x"}
    out = _described("app_alert.backup_health.usb_stale.title", "backup_health.usb_backup", stored=[own])
    assert [a["id"] for a in out["actions"]] == ["own", "recheck", "open_backups"]


def test_source_label_icon_and_name() -> None:
    out = kinds.describe(1, "backup_health.usb_backup", "backup_health", "error", "app_alert.backup_health.usb_stale.title",
                         {"plugin": "obsidian-export"}, [], None)
    assert out["source_label_key"] == "app_alert.source.backup_health" and out["source_icon"] == "database"
    assert out["source_name"] == "obsidian-export"
    agent = kinds.describe(2, "k", "mystery", "info", "app_alert.x.title", {"agent": "Cv-Misc UI"}, [], None)
    assert agent["source_name"] == "Cv-Misc UI" and agent["source_label_key"] == "app_alert.source.other"
    assert agent["kind"] == kinds.FYI


def test_every_declared_string_is_in_the_catalog_and_every_action_is_valid() -> None:
    declared = [d for d in kinds.BY_TITLE.values()] + [d for _, d in kinds.BY_KEY_PREFIX]
    for entry in declared:
        for action in _walk([dict(a) for a in entry.actions]):
            validate_action(kinds._fill(action, 1))
            assert action["label_key"] in CATALOG_KEYS, action["label_key"]
        if entry.default_detail_key:
            assert entry.default_detail_key in CATALOG_KEYS
    assert {s.label_key for s in kinds.SOURCES.values()} <= CATALOG_KEYS
    assert kinds.FALLBACK_SOURCE.label_key in CATALOG_KEYS
    assert {f"app_alert.kind.{k}" for k in kinds.KINDS} <= CATALOG_KEYS


def test_recheck_is_declared_only_where_a_producer_can_run_it() -> None:
    for title, entry in kinds.BY_TITLE.items():
        if any(a["id"] == "recheck" for a in _walk([dict(a) for a in entry.actions])):
            assert recheck.supports(_key_for(title).split(".")[0] + ".x"), title
    assert not recheck.supports("pipeline.llm_all_down")


def test_a_malformed_explainer_is_refused() -> None:
    with pytest.raises(AlertInputError):
        validate_action({"id": "x", "label_key": "app_alert.a", "explain_key": "app_alert.b"})
    with pytest.raises(AlertInputError):
        validate_action({"id": "x", "label_key": "app_alert.a", "explain_key": "nope", "actions": []})
