
from __future__ import annotations

import ast
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parent.parent / "src" / "main.py"


def _find_uvicorn_run_call(tree: ast.Module) -> ast.Call:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "uvicorn"
        ):
            return node
    raise AssertionError(
        "src/main.py no longer contains a uvicorn.run(...) call - "
        "this test needs updating, but first confirm reload is still "
        "not hardcoded on wherever the server is started."
    )


def test_uvicorn_run_reload_is_not_hardcoded_true():
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"), filename=str(MAIN_PY))
    call = _find_uvicorn_run_call(tree)

    reload_kwarg = None
    for kw in call.keywords:
        if kw.arg == "reload":
            reload_kwarg = kw
            break

    assert reload_kwarg is not None, (
        "uvicorn.run(...) in src/main.py no longer passes reload= "
        "explicitly - uvicorn defaults reload to False, which is safe, "
        "but make it explicit so this stays auditable."
    )

    value = reload_kwarg.value
    is_hardcoded_constant = isinstance(value, ast.Constant) and isinstance(
        value.value, bool
    )
    assert not is_hardcoded_constant, (
        "uvicorn.run(..., reload=...) in src/main.py is a hardcoded "
        f"boolean literal ({value.value!r}), not a config-driven value. "
        "Production must never run a file-watching reloader - point "
        "reload= at settings.dev_reload (CLOUDE_DEV_RELOAD env var, "
        "defaulting False) instead of a constant."
    )


def test_dev_reload_setting_defaults_false(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDE_DEV_RELOAD", raising=False)
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TOTP_SECRET", "testsecretnotreal")
    monkeypatch.setenv("JWT_SECRET", "testjwtnotreal")
    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.dev_reload is False, (
        "Settings.dev_reload defaulted to True with CLOUDE_DEV_RELOAD "
        "unset - this must default False so a deployed .env that "
        "never mentions the var still gets a non-reloading server."
    )


def _bootstrap_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TOTP_SECRET", "testsecretnotreal")
    monkeypatch.setenv("JWT_SECRET", "testjwtnotreal")
    for name in ("CARNIVORE_DEV_RELOAD", "CLOUDE_DEV_RELOAD", "CLOUDECODE_DEV_RELOAD"):
        monkeypatch.delenv(name, raising=False)


def test_dev_reload_resolves_from_new_carnivore_name_alone(monkeypatch, tmp_path):
    _bootstrap_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CARNIVORE_DEV_RELOAD", "true")

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.dev_reload is True, (
        "Settings.dev_reload did not resolve from CARNIVORE_DEV_RELOAD "
        "alone - the new-style env var name must work with zero legacy "
        "var present."
    )


def test_dev_reload_resolves_from_legacy_cloude_name_alone(monkeypatch, tmp_path):
    _bootstrap_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUDE_DEV_RELOAD", "true")

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.dev_reload is True, (
        "Settings.dev_reload stopped resolving from the legacy "
        "CLOUDE_DEV_RELOAD var - Phase 2 must be additive, never a "
        "cutover that breaks an existing .env."
    )


def test_dev_reload_new_name_wins_over_legacy_when_both_set(monkeypatch, tmp_path):
    _bootstrap_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CARNIVORE_DEV_RELOAD", "true")
    monkeypatch.setenv("CLOUDE_DEV_RELOAD", "false")

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.dev_reload is True, (
        "CARNIVORE_DEV_RELOAD must take precedence over CLOUDE_DEV_RELOAD "
        "when both are set - current name wins, per AliasChoices order."
    )
