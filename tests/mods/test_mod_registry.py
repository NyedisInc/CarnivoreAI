
import json
import os
from pathlib import Path

from src.core.mods import inventory, registry

KEY = registry.ENV_KEY
OTHER = "/opt/other-plugin"


def _env(path: Path):
    return json.loads(path.read_text()).get("env", {})


def _world(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".claude" / "mods" / "alpha" / "hooks").mkdir(parents=True)
    (home / ".claude" / "mods" / "alpha" / "hooks" / "hooks.json").write_text('{"modules": ["./register.js"]}')
    primary = home / ".claude" / "settings.json"
    primary.write_text(json.dumps({"theme": "dark", "env": {"KEEP": "1", KEY: OTHER}}, indent=2))
    accounts = tmp_path / "accounts"
    files = []
    for name in ("a", "b"):
        (accounts / name).mkdir(parents=True)
        (accounts / name / "settings.json").symlink_to(primary)
        files.append(accounts / name / "settings.json")
    (accounts / "c").mkdir()
    (accounts / "c" / "settings.json").write_text(json.dumps({"x": 1}))
    files.append(accounts / "c" / "settings.json")
    (accounts / "gone").mkdir()
    files.append(accounts / "gone" / "settings.json")
    return home, primary, files


def test_register_unregister_symlinks_dedupe_missing(tmp_path):
    home, primary, files = _world(tmp_path)
    mod = str(home / ".claude" / "mods" / "alpha")
    results = registry.register(mod, home=home, account_files=files)
    assert [r["status"] for r in results] == ["ok", "ok", "settings_missing"]
    assert len(results[0]["members"]) == 3
    assert all(f.is_symlink() for f in files[:2]) and primary.is_file() and not primary.is_symlink()
    doc = json.loads(primary.read_text())
    assert doc["theme"] == "dark" and doc["env"]["KEEP"] == "1"
    assert doc["env"][KEY] == f"{OTHER}:{mod}"
    assert _env(files[2])[KEY] == mod and json.loads(files[2].read_text())["x"] == 1
    assert not files[3].exists()
    link = tmp_path / "link"
    link.symlink_to(mod)
    registry.register(str(link), home=home, account_files=files)
    assert _env(primary)[KEY] == f"{OTHER}:{mod}"
    registry.unregister(mod, home=home, account_files=files)
    assert _env(primary) == {"KEEP": "1", KEY: OTHER}
    assert _env(files[2]) == {}
    registry.unregister(OTHER, home=home, account_files=files)
    assert _env(primary) == {"KEEP": "1"}
    assert all(f.is_symlink() for f in files[:2])


def test_unparseable_left_untouched_and_inventory(tmp_path):
    home, primary, files = _world(tmp_path)
    files[2].write_text("{not json")
    mod = str(home / ".claude" / "mods" / "alpha")
    results = registry.register(mod, home=home, account_files=files)
    assert [r["status"] for r in results] == ["ok", "settings_unparseable", "settings_missing"]
    assert files[2].read_text() == "{not json"
    inv = inventory.build_inventory(home, files, [])
    entry = next(m for m in inv["mods"] if m["path"] == mod)
    assert (entry["state"], entry["registered_in"], entry["groups_total"], entry["removable"]) == ("partial", 1, 3, True)
    assert [g["status"] for g in inv["groups"]] == ["ok", "settings_unparseable", "settings_missing"]
    assert any(m["path"] == OTHER and m["is_mod"] is False and not m["present"] for m in inv["mods"])


def test_no_second_writer_of_the_key():
    root = Path(__file__).resolve().parents[2] / "src"
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py") if KEY in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == ["core/mods/registry.py"]


def test_account_settings_files_from_config(tmp_path, monkeypatch):
    import types

    from src.api import mods_routes

    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "acct-a", "name": "A", "provider": "claude", "managed": True},
        {"id": "acct-b", "name": "B", "provider": "claude", "claude_config_dir": "~/.claude-b"},
        {"id": "acct-c", "name": "C", "provider": "codex", "managed": True},
    ]}}))
    monkeypatch.setattr(mods_routes, "settings", types.SimpleNamespace(auth_config_file=str(cfg)))
    files, status = mods_routes.account_settings_files()
    assert status == "ok" and len(files) == 2
    assert files[1] == tmp_path / ".claude-b" / "settings.json"
    assert all(isinstance(f, Path) and str(f).startswith(str(tmp_path)) for f in files)
    cfg.write_text("{bad")
    assert mods_routes.account_settings_files() == ([], "accounts_unreadable")


def test_failed_backup_is_named_and_dotdot_is_not_removable(tmp_path, monkeypatch):
    home, primary, files = _world(tmp_path)
    mod = str(home / ".claude" / "mods" / "alpha")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(registry.config_writer, "_write_backup", boom)
    results = registry.register(mod, home=home, account_files=[])
    assert results[0]["status"] == "settings_unwritable" and _env(primary)[KEY] == OTHER
    monkeypatch.undo()
    root = inventory.mods_root(home)
    assert inventory.is_directly_under(mod, root)
    assert not inventory.is_directly_under(str(root / "alpha" / ".." / "alpha"), root)
