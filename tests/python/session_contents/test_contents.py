
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.account_switch.pane_account import PaneProfile
from src.core.bookmarks import rows
from src.core.session_contents import claude, codex
from src.core.session_contents import constants as C
from src.core.session_contents import gather
from tests.python.bookmarks import fixtures

SECRETS = ("s3cr3t-value", "ghp_secretvalue", "abc123", "token=zzz", "Bearer", "SECRETTOKEN", "--x")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skill(root: Path, name: str, desc: str) -> None:
    _write(root / name / "SKILL.md", f"---\nname: {name}\ndescription: {desc}\n---\nbody\n")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(C, "CLAUDE_MANAGED_DIRS", ())
    cfg, plug = tmp_path / "cfg", tmp_path / "plug"
    wd = tmp_path / "proj" / "sub"
    _write(cfg / "CLAUDE.md", "# global\nsee @extra.md and mail me@example.com\n")
    _write(cfg / "extra.md", "imported\n")
    _skill(cfg / "skills", "alpha", "the alpha skill")
    _write(cfg / "agents" / "helper.md", "---\ndescription: helps out\n---\n")
    _write(cfg / "commands" / "my" / "cb.md", "---\ndescription: a command\n---\n")
    _write(cfg / "output-styles" / "terse.md", "---\ndescription: short\n---\n")
    _write(cfg / "settings.json", json.dumps({
        "env": {"SECRET": "s3cr3t-value"}, "enabledPlugins": {"pl@mk": True},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "TOKEN=abc123 /usr/bin/guard.sh --x"}]}]}}))
    _write(cfg / ".claude.json", json.dumps({
        "mcpServers": {"gh": {"command": "/usr/bin/npx", "args": ["-y", "x"], "env": {"GITHUB_TOKEN": "ghp_secretvalue"}},
                       "remote": {"type": "http", "url": "https://x.example/mcp?token=zzz",
                                  "headers": {"Authorization": "Bearer abc"}}},
        "projects": {str(wd): {"mcpServers": {"localsrv": {"command": "node"}}}}}))
    _write(cfg / "plugins" / "installed_plugins.json", json.dumps(
        {"version": 2, "plugins": {"pl@mk": [{"scope": "user", "installPath": str(plug), "version": "1.2.3"}]}}))
    _skill(plug / "skills", "pskill", "from the plugin")
    _write(plug / "commands" / "pc.md", "plugin command\n")
    _write(plug / ".mcp.json", json.dumps({"mcpServers": {"pmcp": {"command": "python3"}}}))
    _write(tmp_path / "proj" / "CLAUDE.md", "# project\n")
    _write(wd / "CLAUDE.local.md", "# local\n")
    _skill(tmp_path / "proj" / ".claude" / "skills", "pj", "project skill")
    _write(wd / ".mcp.json", json.dumps({"mcpServers": {"filesys": {"command": "npx"}}}))
    _write(wd / ".claude" / "settings.local.json", json.dumps({"permissions": {}}))
    codex = tmp_path / "codex"
    _write(codex / "AGENTS.md", "# codex global\n")
    _write(codex / "auth.json", '{"token": "SECRETTOKEN"}')
    _write(codex / "prompts" / "review.md", "---\ndescription: review it\n---\n")
    _skill(codex / "skills", "cskill", "codex skill")
    _write(codex / "config.toml", 'model = "gpt"\n[profiles.fast]\nmodel = "mini"\n'
           '[mcp_servers.ctx]\ncommand = "/bin/uvx"\nargs = ["--x"]\n[mcp_servers.ctx.env]\nK = "SECRETTOKEN"\n')
    (wd.parent / ".git").mkdir()
    _write(wd / "AGENTS.md", "# project agents\n")
    return {"cfg": cfg, "wd": wd, "codex": codex, "tmp": tmp_path}


def _by_kind(sections):
    return {s["kind"]: {i["name"]: i for i in s["items"]} for s in sections}


def test_claude_contents_cover_every_section_with_scopes(tree):
    kinds = _by_kind(claude.gather(str(tree["cfg"]), str(tree["wd"])))
    assert kinds["instructions"]["CLAUDE.md"]["scope"] in ("global", "project")
    assert {"CLAUDE.md", "extra.md", "CLAUDE.local.md"} <= set(kinds["instructions"])
    assert "imported by CLAUDE.md" in kinds["instructions"]["extra.md"]["detail"]
    assert kinds["skills"]["alpha"]["scope"] == "global"
    assert kinds["skills"]["alpha"]["description"] == "the alpha skill"
    assert kinds["skills"]["pj"]["scope"] == "project" and kinds["skills"]["pskill"]["scope"] == "plugin"
    assert kinds["agents"]["helper"]["description"] == "helps out"
    assert {"my:cb", "pc"} <= set(kinds["commands"])
    assert "terse" in kinds["output_styles"]
    assert kinds["hooks"]["PreToolUse [Bash]"]["detail"] == "command guard.sh"
    assert {"settings.json", "settings.local.json"} <= set(kinds["settings"])
    assert kinds["mcp"]["gh"]["detail"] == "stdio npx" and kinds["mcp"]["remote"]["detail"] == "http"
    assert kinds["mcp"]["localsrv"]["scope"] == "project" and kinds["mcp"]["filesys"]["scope"] == "project"
    assert kinds["mcp"]["pmcp"]["scope"] == "plugin"
    assert kinds["plugins"]["pl"]["detail"] == "v1.2.3 enabled"


def test_codex_contents_read_agents_prompts_config_but_never_auth(tree):
    sections = codex.gather(str(tree["codex"]), str(tree["wd"]))
    kinds = _by_kind(sections)
    assert [s["kind"] for s in sections] == list(C.SECTIONS_BY_FAMILY["codex"])
    assert {i["scope"] for i in sections[0]["items"]} == {"global", "project"}
    assert kinds["prompts"]["review"]["description"] == "review it"
    assert kinds["skills"]["cskill"]["scope"] == "global"
    assert kinds["profiles"]["fast"]["detail"] == "mini"
    assert kinds["mcp"]["ctx"]["detail"] == "stdio uvx"
    assert "auth.json" not in json.dumps(sections)


@pytest.fixture
def client(tree, monkeypatch):
    from src.api.routes import router

    db = fixtures.make_datastore(tree["tmp"] / "cloude.db")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE sessions SET working_dir = ?", (str(tree["wd"]),))
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(rows, "family_of", lambda agent_type: agent_type)
    state = {"value": str(tree["cfg"])}

    async def fake_profile(socket, tmux_name, variable):
        return PaneProfile(readable=True, value=state["value"])

    monkeypatch.setattr(gather, "read_pane_profile", fake_profile)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    test_client = TestClient(app)
    test_client.state, test_client.db = state, db
    return test_client


def test_route_answers_by_row_id_and_carries_no_secret(client, tree):
    resp = client.get("/api/v1/sessions/7/contents")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["family"] == "claude" and body["config_dir"] == str(tree["cfg"])
    assert [s["kind"] for s in body["sections"]] == list(C.SECTIONS_BY_FAMILY["claude"])
    assert not [s for s in SECRETS if s in resp.text]
    assert client.get("/api/v1/sessions/row-uuid-1/contents").json()["row_id"] == 7


def test_route_refusals_are_named(client, tree):
    assert client.get("/api/v1/sessions/999/contents").json()["detail"]["code"] == "session_not_found"
    with sqlite3.connect(client.db) as conn:
        conn.execute("UPDATE sessions SET agent_type = 'shell'")
    assert client.get("/api/v1/sessions/7/contents").json()["detail"]["code"] == "unsupported_family"
    with sqlite3.connect(client.db) as conn:
        conn.execute("UPDATE sessions SET agent_type = 'codex', host_key = 'peer-x'")
    resp = client.get("/api/v1/sessions/7/contents")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "remote_host"


def test_codex_session_uses_its_codex_home(client, tree):
    client.state["value"] = str(tree["codex"])
    with sqlite3.connect(client.db) as conn:
        conn.execute("UPDATE sessions SET agent_type = 'codex'")
    body = client.get("/api/v1/sessions/7/contents").json()
    assert body["family"] == "codex" and body["config_dir"] == str(tree["codex"])
    assert "SECRETTOKEN" not in json.dumps(body)


def test_enrich_adds_lines_open_target_and_status(tree, monkeypatch):
    from src.core import config_files
    from src.core.session_contents.enrich import enrich

    monkeypatch.setattr(config_files, "CLAUDE_HOME", tree["cfg"])
    sections = enrich(claude.gather(str(tree["cfg"]), str(tree["wd"])), str(tree["wd"]))
    kinds = _by_kind(sections)
    local = kinds["instructions"]["CLAUDE.local.md"]
    assert (local["lines"], local["open_root"], local["open_path"]) == (1, "workdir", "CLAUDE.local.md")
    assert local["status"] == "loaded"
    alpha = kinds["skills"]["alpha"]
    assert alpha["open_root"] == "user" and alpha["open_path"] == "skills/alpha/SKILL.md"
    assert kinds["instructions"]["extra.md"]["lines"] == 1 and kinds["instructions"]["extra.md"]["open_root"] is None
    assert kinds["skills"]["alpha"]["status"] == "available" and kinds["skills"]["alpha"]["lines"] == 5
    assert kinds["plugins"]["pl"]["lines"] is None and kinds["plugins"]["pl"]["open_root"] is None
    assert kinds["mcp"]["gh"]["lines"] is None and kinds["mcp"]["gh"]["open_root"] is None
    assert kinds["mcp"]["filesys"]["open_root"] == "workdir" and kinds["hooks"]["PreToolUse [Bash]"]["lines"] is None


def test_enrich_marks_a_disabled_plugin_and_counts_an_unterminated_last_line(tmp_path):
    from src.core.session_contents import enrich as E

    f = tmp_path / "a.md"
    f.write_text("one\ntwo", encoding="utf-8")
    assert E.count_lines(f) == 2 and E.count_lines(tmp_path / "missing.md") is None and E.count_lines(tmp_path) is None
    assert E.status_of("skills", "plugin x (disabled)") == "disabled"
    assert E.status_of("plugins", "v1 not enabled") == "disabled" and E.status_of("plugins", "v1 enabled") == "available"
    assert E.open_target(None, str(tmp_path)) == (None, None) and E.open_target("/etc/hosts", str(tmp_path)) == (None, None)


def test_route_items_carry_the_new_fields_and_never_a_file_body(client, tree, monkeypatch):
    from src.core import config_files

    monkeypatch.setattr(config_files, "CLAUDE_HOME", tree["cfg"])
    body = client.get("/api/v1/sessions/7/contents").json()
    item = next(i for s in body["sections"] if s["kind"] == "instructions" for i in s["items"] if i["name"] == "CLAUDE.local.md")
    assert item["lines"] == 1 and item["open_root"] == "workdir" and item["status"] == "loaded"
    assert "# local" not in json.dumps(body)
