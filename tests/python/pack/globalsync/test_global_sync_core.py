
from __future__ import annotations

import asyncio
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

from src.core.pack.globalsync import apply as gs_apply, collect, sender
from src.core.pack.globalsync.store import Status
from src.core.pack.transport import blobs

SECRET = "-".join(["sk", "ant", "api03", "YxPo0C", "rT7qLw3nZ8vB5kM2", "jH9dGfS1aQeU4iXc", "V6tNyRbWp"])


def make_home(tmp: Path, name: str = "main") -> Path:
    home = tmp / name
    claude = home / ".claude"
    (claude / "skills" / "demo").mkdir(parents=True)
    (claude / "skills" / "demo" / "SKILL.md").write_text(f"see {home}/.claude/skills/demo/run.sh\n")
    (claude / "skills" / "demo" / "node_modules" / "x").mkdir(parents=True)
    (claude / "skills" / "demo" / "node_modules" / "x" / "i.js").write_text("module")
    (claude / "mods" / "bar").mkdir(parents=True)
    (claude / "mods" / "bar" / "mod.json").write_text("{}")
    (claude / "orchestrator").mkdir()
    (claude / "orchestrator" / "orchestrator.md").write_text("rules the global CLAUDE.md points at\n")
    (claude / "hooks").mkdir()
    (claude / "hooks" / "pre.sh").write_text("#!/bin/sh\necho hi\n")
    (claude / "hooks" / "auth.json").write_text('{"token": "x"}')
    (claude / ".credentials.json").write_text('{"claudeAiOauth": {"accessToken": "nope"}}')
    (claude / "CLAUDE.md").write_text("# rules\n")
    (claude / "statusline-command.sh").write_text(f"#!/bin/sh\n{home}/.claude/bin/x\n")
    (claude / "settings.json").write_text(json.dumps({
        "statusLine": {"type": "command", "command": f"{home}/.claude/statusline-command.sh"},
        "env": {"EDITOR": "vim", "MY_API_KEY": SECRET, "PLAIN": "1"},
        "mcpServers": {"s": {"env": {"TOKEN": SECRET, "MODE": "fast"}, "headers": {"Authorization": "Bearer " + SECRET}}}}))
    for per_machine in ("projects", "sessions", "todos", "statsig", "ide", "file-history", "session-env", "shell-snapshots", "plans", "cache", "debug", "backups", "telemetry"):
        (claude / per_machine).mkdir()
        (claude / per_machine / "keep-home.txt").write_text("per machine")
    (claude / "history.jsonl").write_text("{}")
    (claude / "plugins").mkdir()
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({"p": {"installPath": f"{home}/.claude/plugins/cache/p"}}))
    (claude / "plugins" / "cache" / "p").mkdir(parents=True)
    (claude / "plugins" / "cache" / "p" / "plugin.json").write_text("{}")
    (claude / "plugins" / "store").mkdir()
    (claude / "plugins" / "store" / "x").write_text("no")
    codex = home / ".codex"
    codex.mkdir()
    (codex / "auth.json").write_text('{"tokens": {"access_token": "nope"}}')
    (codex / "AGENTS.md").write_text("codex rules\n")
    (codex / "config.toml").write_text('model = "x"\n[mcp_servers.n.env]\nMODE = "fast"\nAPI_KEY = "%s"\n' % SECRET)
    (codex / "sessions").mkdir()
    (codex / "sessions" / "s.jsonl").write_text("{}")
    (codex / "state_5.sqlite").write_text("db")
    return home


def build(home: Path, out: Path) -> collect.Built:
    return collect.build(collect.slots_for(home, [], ["claude", "codex"]), out, home)


def names(path: Path) -> set:
    with tarfile.open(path, "r:gz") as tar:
        return set(tar.getnames())


def members(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar if m.isreg()}


def test_env_secrets_scrubbed_harmless_env_stays(tmp_path):
    home = make_home(tmp_path)
    built = build(home, tmp_path / "b.tgz")
    files = members(built.path)
    settings = json.loads(files["claude.default/settings.json"])
    assert settings["env"] == {"EDITOR": "vim", "PLAIN": "1"}
    assert settings["mcpServers"]["s"]["env"] == {"MODE": "fast"}
    assert settings["mcpServers"]["s"]["headers"] == {}
    toml = files["codex.default/config.toml"].decode()
    assert 'MODE = "fast"' in toml and "API_KEY" not in toml and 'model = "x"' in toml
    assert built.scrubbed >= 4
    assert not any(SECRET.encode() in blob for blob in files.values())
    assert all(SECRET not in str(r) for r in built.refused)


def test_credential_files_never_leave(tmp_path):
    built = build(make_home(tmp_path), tmp_path / "b.tgz")
    got = names(built.path)
    assert not any(n.endswith(("auth.json", ".credentials.json")) for n in got)
    refused = {r[0] for r in built.refused}
    assert "claude.default/hooks/auth.json" in refused


def test_per_machine_dirs_excluded(tmp_path):
    got = names(build(make_home(tmp_path), tmp_path / "b.tgz").path)
    for banned in ("projects", "sessions", "todos", "statsig", "ide", "file-history", "session-env", "shell-snapshots", "plans", "debug", "backups", "telemetry", "history.jsonl", "state_5.sqlite", "node_modules", "plugins/store"):
        assert not any(banned in n for n in got), banned
    assert "claude.default/skills/demo/SKILL.md" in got and "claude.default/mods/bar/mod.json" in got
    assert not any(n.startswith("claude.default/cache/") for n in got)
    assert "claude.default/orchestrator/orchestrator.md" in got
    assert "claude.default/plugins/cache/p/plugin.json" in got and "claude.default/hooks/pre.sh" in got


def test_home_paths_rewritten_to_receiver_home(tmp_path):
    main, other = make_home(tmp_path), tmp_path / "member"
    (other / ".claude").mkdir(parents=True)
    built = build(main, tmp_path / "b.tgz")
    assert str(main).encode() not in b"".join(members(built.path).values())
    state = gs_apply.State(tmp_path / "state.json")
    gs_apply.apply_bundle(built.path, home=other, accounts_root=other / ".carnivore" / "accounts", accounts=[], state=state,
                          backups=tmp_path / "bk", stage_root=tmp_path)
    assert (other / ".claude" / "skills" / "demo" / "SKILL.md").read_text() == f"see {other}/.claude/skills/demo/run.sh\n"
    assert json.loads((other / ".claude" / "settings.json").read_text())["statusLine"]["command"] == f"{other}/.claude/statusline-command.sh"
    assert json.loads((other / ".claude" / "plugins" / "installed_plugins.json").read_text())["p"]["installPath"].startswith(str(other))


def test_receiver_backs_up_before_overwrite_keeps_local_env_and_removes_dropped(tmp_path):
    main, member = make_home(tmp_path), tmp_path / "member"
    claude = member / ".claude"
    claude.mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("member's own rules\n")
    (claude / "settings.json").write_text(json.dumps({"env": {"MEMBER_KEY": SECRET}, "theme": "dark"}))
    (member / ".claude" / "skills").mkdir()
    (member / ".claude" / "skills" / "member-only.md").write_text("keep me")
    state = gs_apply.State(tmp_path / "state.json")
    args = dict(home=member, accounts_root=member / ".carnivore" / "accounts", accounts=[], state=state, backups=tmp_path / "bk", stage_root=tmp_path)
    first = gs_apply.apply_bundle(build(main, tmp_path / "b1.tgz").path, **args)
    assert first.backup is not None
    backed = {p.name: p.read_text() for p in Path(first.backup).rglob("*") if p.is_file()}
    assert backed["CLAUDE.md"] == "member's own rules\n"
    assert "MEMBER_KEY" in backed["settings.json"]
    assert (claude / "CLAUDE.md").read_text() == "# rules\n"
    merged = json.loads((claude / "settings.json").read_text())
    assert merged["env"]["MEMBER_KEY"] == SECRET and merged["env"]["EDITOR"] == "vim"
    assert (claude / "skills" / "member-only.md").read_text() == "keep me"
    (main / ".claude" / "mods" / "bar" / "mod.json").unlink()
    second = gs_apply.apply_bundle(build(main, tmp_path / "b2.tgz").path, **args)
    assert second.removed == 1 and not (claude / "mods" / "bar" / "mod.json").exists()
    third = gs_apply.apply_bundle(build(main, tmp_path / "b3.tgz").path, **args)
    assert third.written == 0 and third.backup is None


def test_receiver_never_writes_through_a_link(tmp_path):
    main, member = make_home(tmp_path), tmp_path / "member"
    outside = tmp_path / "outside"
    outside.mkdir()
    (member / ".claude").mkdir(parents=True)
    (member / ".claude" / "skills").symlink_to(outside)
    report = gs_apply.apply_bundle(build(main, tmp_path / "b.tgz").path, home=member, accounts_root=member / "a", accounts=[],
                                   state=gs_apply.State(tmp_path / "s.json"), backups=tmp_path / "bk", stage_root=tmp_path)
    assert list(outside.iterdir()) == []
    assert any(r[1] == "link" for r in report.refused)


def _gate_fixture(tmp_path, *, approved: bool, opted_in, enabled: bool = True):
    home = make_home(tmp_path)
    sent: list = []

    async def request(method, path, **kw):
        sent.append((method, path))
        return 200, {"report": {"written": 1}}

    async def fake_send(req, path, **kw):
        sent.append(("BLOB", kw.get("base_path")))
        return kw["blob_id"]

    view = sender.PeerView("iid-b", "member", True, [sender.CAP])
    box = sender.GlobalSync(
        settings=lambda: {"enabled": enabled, "auto": False, "claude": True, "codex": True}, is_main=lambda: True, peers=lambda: [view],
        approved=lambda iid: approved, allows=lambda iid: opted_in, contained=lambda iid: False, accounts=lambda: [],
        request_for=lambda iid, timeout: request, status=Status(tmp_path / "status.json"), outbox=tmp_path / "out", home=home, notify=lambda: None)
    return box, sent


def run_sync(box, monkeypatch):
    monkeypatch.setattr(blobs, "send_file", _blob_send)
    return asyncio.run(box.sync(["iid-b"], force=True))


async def _blob_send(req, path, **kw):
    await req("PUT", kw["base_path"])
    return kw["blob_id"]


def test_nothing_is_sent_without_approval_and_receiver_opt_in(tmp_path, monkeypatch):
    for approved, opted, reason in ((False, True, "not_approved"), (True, False, "receiver_off"), (True, None, "receiver_off"), (False, False, "not_approved")):
        box, sent = _gate_fixture(tmp_path / f"{approved}{opted}", approved=approved, opted_in=opted)
        assert run_sync(box, monkeypatch) == {"iid-b": reason}
        assert sent == [] and box.status.get("iid-b")["reason"] == reason
    off, sent = _gate_fixture(tmp_path / "off", approved=True, opted_in=True, enabled=False)
    assert run_sync(off, monkeypatch) == {} and sent == []
    box, sent = _gate_fixture(tmp_path / "ok", approved=True, opted_in=True)
    assert run_sync(box, monkeypatch) == {"iid-b": "synced"}
    assert ("POST", sender.APPLY_PATH) in sent and box.status.get("iid-b")["state"] == "synced"
