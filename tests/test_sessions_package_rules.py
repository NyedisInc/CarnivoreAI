
from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "core" / "sessions"

MAX_LINES = 1000

FORBIDDEN_IMPORT = "session_manager"

SETTINGS_MODULE = "src.config"
SETTINGS_SINGLETON = "settings"


def _package_modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_exists_and_holds_modules():
    assert PACKAGE.is_dir(), f"{PACKAGE} is missing"
    modules = _package_modules()
    assert modules, "the package holds no modules, so the rules below tested nothing"


def _check_no_session_manager_import(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                a.name for a in node.names if FORBIDDEN_IMPORT in a.name
            ]
        elif isinstance(node, ast.ImportFrom):
            if node.module and FORBIDDEN_IMPORT in node.module:
                offenders.append(node.module)

    assert offenders == [], (
        f"{module.name} imports {offenders}; nothing under src/core/sessions/ "
        "may depend on the facade"
    )


def test_no_collaborator_imports_the_session_manager():
    assert_no_offenders("no import of session_manager", _package_modules(),
                        _check_no_session_manager_import, label=lambda p: p.name)


def _check_line_guideline(module: Path) -> None:
    lines = len(module.read_text(encoding="utf-8").splitlines())

    assert lines <= MAX_LINES, (
        f"{module.name} is {lines} lines, over the {MAX_LINES}-line guideline; "
        "split it rather than raising the number"
    )


def test_no_collaborator_exceeds_the_line_guideline():
    assert_no_offenders("collaborator line guideline", _package_modules(),
                        _check_line_guideline, label=lambda p: p.name)


def test_no_collaborator_imports_the_settings_singleton():
    def check(module: Path) -> None:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"import {a.name}"
                    for a in node.names
                    if a.name == SETTINGS_MODULE or a.name.startswith(SETTINGS_MODULE + ".")
                ]
            elif isinstance(node, ast.ImportFrom):
                if node.module == SETTINGS_MODULE:
                    offenders += [
                        f"from {node.module} import {a.name}"
                        for a in node.names
                        if a.name == SETTINGS_SINGLETON
                    ]
        assert offenders == [], (
            f"{module.name} does {offenders}; a collaborator takes a "
            "SettingsReader from the composition root, because the suite "
            "patches the settings name somewhere this module cannot see"
        )

    assert_no_offenders("no import of the settings singleton", _package_modules(),
                        check, label=lambda p: p.name)
