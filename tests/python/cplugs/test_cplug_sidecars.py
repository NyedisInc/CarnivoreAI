
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import structlog

from src.cplugs.host import runtime
from src.cplugs.sdk import sidecar
from src.cplugs.sdk.manifest import parse_manifest
from tests.helpers.catalog_text import catalog_text

ROOT = Path(__file__).resolve().parents[3]
PLUGINS = ROOT / "src" / "cplugs"
SHIPPED = [d.id for d in runtime.definitions()]


def _copy(plugin_id: str, tmp_path: Path) -> Path:
    folder = tmp_path / plugin_id
    folder.mkdir()
    for name in ("cplug.json", sidecar.SIDECAR_NAME):
        if (PLUGINS / plugin_id / name).is_file():
            shutil.copy(PLUGINS / plugin_id / name, folder / name)
    return folder


def _manifest(folder: Path):
    return parse_manifest(json.loads((folder / "cplug.json").read_text()))


def test_every_shipped_plugin_but_the_pending_ones_has_a_valid_sidecar() -> None:
    reports = sidecar.audit_ship_list((d.manifest for d in runtime.definitions()), PLUGINS)
    assert set(reports) == set(SHIPPED)
    bad = {k: (r.status, r.problems) for k, r in reports.items() if r.status != sidecar.VALID}
    assert set(bad) == set(sidecar.PENDING), bad
    assert all(bad[k][0] == sidecar.MISSING for k in bad), "a pending plugin may be missing its sidecar, not carry a broken one"


def test_no_plugin_awaits_a_sidecar_and_huddle_carries_one() -> None:
    assert set(sidecar.PENDING) == set()
    assert (PLUGINS / "huddle" / sidecar.SIDECAR_NAME).is_file()


@pytest.mark.parametrize("plugin_id", [i for i in SHIPPED if i not in sidecar.PENDING])
def test_the_sidecar_name_is_the_catalog_name_the_plugins_page_draws(plugin_id: str) -> None:
    doc = json.loads((PLUGINS / plugin_id / sidecar.SIDECAR_NAME).read_text())
    match = re.search(r"'cplug\.%s\.name': '((?:[^'\\]|\\.)*)'" % plugin_id, catalog_text())
    assert match and match.group(1) == doc["name"], f"{plugin_id}: sidecar name {doc['name']!r} vs catalog"
    assert doc["id"] == plugin_id and doc["kind"] == "cplug"


def test_a_missing_sidecar_warns_with_the_plugin_and_the_pending_reason(tmp_path: Path) -> None:
    folder = _copy("share", tmp_path)
    (folder / sidecar.SIDECAR_NAME).unlink()
    with structlog.testing.capture_logs() as logs:
        reports = sidecar.audit_ship_list([_manifest(folder)], tmp_path, enforcement="warn")
    assert reports["share"].status == sidecar.MISSING
    event = next(e for e in logs if e["event"] == "cplug_sidecar_missing")
    assert event["cplug"] == "share" and event["log_level"] == "warning" and event["enforcement"] == "warn"


def test_a_valid_sidecar_warns_about_nothing(tmp_path: Path) -> None:
    folder = _copy("share", tmp_path)
    with structlog.testing.capture_logs() as logs:
        reports = sidecar.audit_ship_list([_manifest(folder)], tmp_path)
    assert reports["share"].status == sidecar.VALID and reports["share"].name == "share read only"
    assert [e for e in logs if e["event"].startswith("cplug_sidecar")] == []


def test_an_invalid_sidecar_warns_with_the_schema_problems(tmp_path: Path) -> None:
    folder = _copy("share", tmp_path)
    doc = json.loads((folder / sidecar.SIDECAR_NAME).read_text())
    doc["tier"] = "core"
    del doc["api_version"]
    (folder / sidecar.SIDECAR_NAME).write_text(json.dumps(doc))
    with structlog.testing.capture_logs() as logs:
        report = sidecar.audit_ship_list([_manifest(folder)], tmp_path)["share"]
    assert report.status == sidecar.INVALID
    assert any("api_version" in p for p in report.problems) and any("tier" in p for p in report.problems)
    assert any(e["event"] == "cplug_sidecar_invalid" and e["cplug"] == "share" for e in logs)


def test_a_sidecar_that_is_not_json_is_invalid_not_a_crash(tmp_path: Path) -> None:
    folder = _copy("share", tmp_path)
    (folder / sidecar.SIDECAR_NAME).write_text("{not json")
    assert sidecar.check_plugin(_manifest(folder), folder).status == sidecar.INVALID


@pytest.mark.parametrize("field, value", [("version", "9.9.9"), ("author", "Someone Else"), ("icon", "zzz"), ("default_enabled", False)])
def test_a_sidecar_that_disagrees_with_cplug_json_is_reported(tmp_path: Path, field: str, value: object) -> None:
    folder = _copy("share", tmp_path)
    doc = json.loads((folder / sidecar.SIDECAR_NAME).read_text())
    doc[field] = value
    (folder / sidecar.SIDECAR_NAME).write_text(json.dumps(doc))
    report = sidecar.check_plugin(_manifest(folder), folder)
    assert report.status == sidecar.DISAGREES and any(p.startswith(field) for p in report.problems)


def test_permissions_requires_and_owns_must_agree_too(tmp_path: Path) -> None:
    folder = _copy("save", tmp_path)
    original = json.loads((folder / sidecar.SIDECAR_NAME).read_text())
    for mutate, needle in (
        (lambda d: d["permissions"].pop(), "permissions"),
        (lambda d: d["permissions"][0].update(reason="a different reason"), "reasons"),
        (lambda d: d.update(requires=[]), "requires"),
        (lambda d: d["owns"].update(files=["elsewhere"]), "owns"),
    ):
        doc = json.loads(json.dumps(original))
        mutate(doc)
        (folder / sidecar.SIDECAR_NAME).write_text(json.dumps(doc))
        report = sidecar.check_plugin(_manifest(folder), folder)
        assert report.status == sidecar.DISAGREES and any(needle in p for p in report.problems), (needle, report)


def test_refuse_mode_raises_and_warn_mode_does_not(tmp_path: Path) -> None:
    folder = _copy("share", tmp_path)
    (folder / sidecar.SIDECAR_NAME).unlink()
    manifest = _manifest(folder)
    assert sidecar.ENFORCEMENT == "warn", "1.0-rc warns; the 1.0 release flips this word and this test with it"
    sidecar.audit_ship_list([manifest], tmp_path, enforcement="warn")
    with pytest.raises(sidecar.SidecarError, match="share: missing"):
        sidecar.audit_ship_list([manifest], tmp_path, enforcement="refuse")


def test_loading_the_real_ship_list_no_longer_warns_about_huddle() -> None:
    runtime._definitions = None
    try:
        with structlog.testing.capture_logs() as logs:
            runtime.definitions()
    finally:
        runtime._definitions = None
        runtime.definitions()
    findings = [e for e in logs if str(e["event"]).startswith("cplug_sidecar_")]
    assert [e for e in findings if e["cplug"] == "huddle"] == []


@pytest.mark.parametrize("plugin_id", SHIPPED)
def test_a_plugin_with_agent_gated_mcp_tools_declares_agent_writes(plugin_id: str):
    mcp_file = PLUGINS / plugin_id / "mcp.py"
    if not mcp_file.is_file() or not re.search(r'gate\s*=\s*"agent(_direct)?"', mcp_file.read_text()):
        pytest.skip("no agent-gated MCP tools")
    manifest = json.loads((PLUGINS / plugin_id / "cplug.json").read_text())
    assert "agent_writes" in manifest.get("permissions", {}).get("app", []), f"{plugin_id} cplug.json"
    side_file = PLUGINS / plugin_id / sidecar.SIDECAR_NAME
    if side_file.is_file():
        side = json.loads(side_file.read_text())
        assert "agent_writes" in [p["name"] for p in side.get("permissions", [])], f"{plugin_id} sidecar"
