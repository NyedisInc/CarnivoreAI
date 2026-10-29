
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fx_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fx_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.api.themes_routes as themes_routes_mod  # noqa: E402
from src.api.auth import require_auth  # noqa: E402

BUNDLED_THEMES_DIR = Path(__file__).resolve().parents[1] / "client" / "css" / "themes"

SHARED_HARNESS = BUNDLED_THEMES_DIR / "_shared" / "effects-base.js"
HARNESS_IMPORT = "../_shared/effects-base.js"


def _theme_dirs() -> list[Path]:
    return sorted(p for p in BUNDLED_THEMES_DIR.iterdir() if (p / "theme.json").is_file())


def _manifests() -> list[tuple[Path, dict]]:
    out = []
    for d in _theme_dirs():
        out.append((d, json.loads((d / "theme.json").read_text(encoding="utf-8"))))
    return out


def _themes_declaring_effects() -> list[tuple[Path, dict]]:
    return [(d, m) for d, m in _manifests() if m.get("effects")]


def test_theme_discovery_finds_a_plausible_number_of_themes() -> None:
    assert len(_theme_dirs()) >= 12


def test_at_least_one_theme_declares_effects() -> None:
    assert _themes_declaring_effects(), "no bundled theme declares an effects module"


def _check_declared_effects_file_exists_on_disk(theme_dir: Path) -> None:
    manifest = json.loads((theme_dir / "theme.json").read_text(encoding="utf-8"))
    target = theme_dir / manifest["effects"]
    assert target.is_file(), f"{theme_dir.name}: declares {manifest['effects']}, not on disk"
    assert target.stat().st_size > 0, f"{theme_dir.name}: effects module is empty"


def test_declared_effects_file_exists_on_disk() -> None:
    assert_no_offenders(
        "declared effects file exists on disk",
        [d for d, _ in _themes_declaring_effects()],
        _check_declared_effects_file_exists_on_disk,
        label=lambda p: p.name,
    )


def _check_declared_effects_value_is_a_bare_filename(theme_dir: Path) -> None:
    manifest = json.loads((theme_dir / "theme.json").read_text(encoding="utf-8"))
    value = manifest["effects"]
    assert isinstance(value, str) and value
    assert "/" not in value, f"{theme_dir.name}: effects must be a bare filename"
    assert "\\" not in value, f"{theme_dir.name}: effects must be a bare filename"
    assert ".." not in value, f"{theme_dir.name}: effects must not traverse"


def test_declared_effects_value_is_a_bare_filename() -> None:
    assert_no_offenders(
        "declared effects value is a bare filename",
        [d for d, _ in _themes_declaring_effects()],
        _check_declared_effects_value_is_a_bare_filename,
        label=lambda p: p.name,
    )


def _check_effects_module_builds_on_the_shared_harness(theme_dir: Path) -> None:
    src = (theme_dir / "effects.js").read_text(encoding="utf-8")
    assert HARNESS_IMPORT in src, (
        f"{theme_dir.name}: effects.js must import {HARNESS_IMPORT}"
    )
    assert "createEffect(" in src, f"{theme_dir.name}: effects.js must call createEffect()"


def test_effects_module_builds_on_the_shared_harness() -> None:
    assert_no_offenders(
        "effects module builds on the shared harness",
        [d for d, _ in _themes_declaring_effects()],
        _check_effects_module_builds_on_the_shared_harness,
        label=lambda p: p.name,
    )


def _check_effects_module_exports_the_loader_contract(theme_dir: Path) -> None:
    src = (theme_dir / "effects.js").read_text(encoding="utf-8")
    assert "export const init" in src, f"{theme_dir.name}: missing init export"
    assert "export const destroy" in src, f"{theme_dir.name}: missing destroy export"
    assert "export default" in src, f"{theme_dir.name}: missing default export"


def test_effects_module_exports_the_loader_contract() -> None:
    assert_no_offenders(
        "effects module exports the loader contract",
        [d for d, _ in _themes_declaring_effects()],
        _check_effects_module_exports_the_loader_contract,
        label=lambda p: p.name,
    )


def test_shared_harness_exists() -> None:
    assert SHARED_HARNESS.is_file()
    assert SHARED_HARNESS.stat().st_size > 0


def test_shared_dir_is_not_discovered_as_a_theme() -> None:
    assert not (SHARED_HARNESS.parent / "theme.json").exists()
    assert SHARED_HARNESS.parent not in _theme_dirs()


def test_no_file_exceeds_the_one_thousand_line_limit() -> None:
    targets = [SHARED_HARNESS] + [d / "effects.js" for d, _ in _themes_declaring_effects()]
    oversized = {
        str(p.relative_to(BUNDLED_THEMES_DIR)): len(p.read_text(encoding="utf-8").splitlines())
        for p in targets
        if len(p.read_text(encoding="utf-8").splitlines()) > 1000
    }
    assert oversized == {}, f"files over 1000 lines: {oversized}"


def test_endpoint_serves_the_effects_field_for_every_declaring_theme() -> None:
    app = FastAPI()
    app.include_router(themes_routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    resp = TestClient(app).get("/api/v1/themes")
    assert resp.status_code == 200
    served = {t["id"]: t for t in resp.json() if t["source"] == "builtin"}

    expected = {d.name: m["effects"] for d, m in _themes_declaring_effects()}
    assert expected, "no bundled theme declares effects"

    for theme_id, filename in expected.items():
        assert theme_id in served, f"{theme_id} was not discovered by the endpoint"
        assert served[theme_id].get("effects") == filename, (
            f"{theme_id}: endpoint served {served[theme_id].get('effects')!r}, "
            f"manifest declares {filename!r}"
        )
