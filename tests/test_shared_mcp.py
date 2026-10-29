
from __future__ import annotations

import json
import os
import queue
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from src.config import settings
from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core import config_writer
from src.core.account_switch import profile_setup, shared_mcp
from src.core.agent_wrappers import AgentWrapper
from src.core.provider_ledger import accounts_store, managed_profiles
from src.core.session_fork import fork_arguments
from src.core.session_resume_target import CONVERSATION_RESUMED, ResumeTarget, resume_extra_args
from src.models.provider_ledger import AccountUsage
from tests.helpers.claude_profile import refuse_writes_outside, temp_home, write_claude_profile

REAL_HOME = os.path.expanduser("~")
ROOT = Path(__file__).resolve().parents[1]
UUID = "0199aa11-bbbb-cccc-dddd-eeeeeeeeeeee"

SECRET_VALUE = "fake-value-that-must-never-be-logged-0123"
SECRET_NAME = "private-billing-server"
UNIQUE_NAME = "only-mine-server"
SECRET_PROJECT = "/w/secret-client-project"

ALPHA = {"type": "stdio", "command": "/bin/echo", "args": ["alpha"], "env": {"API_KEY": SECRET_VALUE}}
BILLING = {"type": "http", "url": "https://example.invalid/mcp", "headers": {"Authorization": SECRET_VALUE}}
MINE = {"type": "stdio", "command": "/bin/echo", "args": ["mine"], "env": {}}
ADDED = {"type": "stdio", "command": "/bin/echo", "args": ["added"], "env": {"TOKEN": SECRET_VALUE}}

DEFAULT_LOGIN = {
    "hasCompletedOnboarding": True,
    "mcpServers": {"alpha": ALPHA, SECRET_NAME: BILLING},
    "projects": {
        "/w/trusted": {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"]},
        "/w/untrusted": {"hasTrustDialogAccepted": False},
        "/w/flip": {"hasTrustDialogAccepted": True},
        SECRET_PROJECT: {"hasTrustDialogAccepted": True},
    },
}


@pytest.fixture(autouse=True)
def second_stop(tmp_path, monkeypatch):
    refused = refuse_writes_outside(tmp_path, monkeypatch)
    yield refused
    assert refused == [], "a real path was reached"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    return temp_home(tmp_path, monkeypatch, default=DEFAULT_LOGIN)


@pytest.fixture()
def config(home, monkeypatch):
    path = home / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    for account_id in ("one", "two"):
        managed_profiles.ensure_managed_dir(account_id)
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider="claude",
            claude_config_dir=managed_dir_for(account_id), managed=True,
        ))
    write_claude_profile(managed_dir_for("one"), extra={
        "mcpServers": {"alpha": ALPHA, SECRET_NAME: BILLING, UNIQUE_NAME: MINE},
        "projects": {"/w/flip": {"hasTrustDialogAccepted": False, "allowedTools": ["x"]},
                     "/w/own": {"hasTrustDialogAccepted": True},
                     "/w/own-false": {"hasTrustDialogAccepted": False}},
    })
    write_claude_profile(managed_dir_for("two"), extra={
        "mcpServers": {"alpha": {**ALPHA, "args": ["alpha", "--mine"]}},
    })
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


def rows(*ids: str):
    return [AccountUsage(id=i, name=i, provider="claude", credential_state="ok") for i in ids]


def converge(config):
    return profile_setup.converge(rows("one", "two"), accounts_store.list_accounts(config))


def profile(account_id: str) -> dict:
    return json.loads((Path(managed_dir_for(account_id)) / ".claude.json").read_text())


def shared_file() -> dict:
    return json.loads(shared_mcp.shared_mcp_path().read_text())


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)



PATH_ARGS = {
    "create": ["--name", "Punchlist Test"],
    "create-bare": None,
    "restart-respawn-recreate-reopen": resume_extra_args(
        ResumeTarget(CONVERSATION_RESUMED, UUID, title="Spike")),
    "fork": fork_arguments(UUID),
}


def wrapper_config(script: str = 'cld() { command claude "$@"; }') -> AgentsConfig:
    return AgentsConfig(wrappers=[AgentWrapper(
        id="cld", label="cld", script=script, entry="cld", default=True,
        accepts_model=False, family="claude",
    )])


def render(tmp_path: Path, agents: AgentsConfig, extra, agent_type: str = "claude", model=None) -> str:
    return agent_command(
        agent_type, agents=agents, resolve_state_dir=lambda: str(tmp_path / "state"),
        disable_alternate_screen=lambda: False, model=model, extra_args=extra,
    )


@pytest.fixture()
def shared_on_disk(tmp_path, monkeypatch) -> Path:
    path = tmp_path / ".claude" / "carnivore-mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"alpha": ALPHA}}))
    monkeypatch.setenv(shared_mcp.SHARED_MCP_PATH_ENV_VAR, str(path))
    return path


@pytest.mark.parametrize("path_name", sorted(PATH_ARGS))
def test_every_launch_path_carries_the_flag_once_inside_the_zsh_command(tmp_path, shared_on_disk, path_name):
    flag = f"--mcp-config={shared_on_disk}"
    extra = PATH_ARGS[path_name]
    wrapped = render(tmp_path, wrapper_config(), extra)
    standard = render(tmp_path, AgentsConfig(), extra)
    for command in (wrapped, standard):
        assert command.count("--mcp-config") == 1, command
        tokens = shlex.split(command)
        assert tokens[:2] == ["zsh", "-c"] and tokens[3] == "_"
        assert tokens[4:] == [flag] + list(extra or [])


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")
@pytest.mark.parametrize("shape", ["wrapper", "standard"])
def test_the_flag_reaches_the_cli_argv_exactly_once(tmp_path, shared_on_disk, shape):
    marker = tmp_path / "argv.txt"
    record = f"printf '%s\\n' \"$@\" > {shlex.quote(str(marker))}"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "claude"
    fake.write_text(f"#!/bin/sh\n{record}\n")
    fake.chmod(0o755)
    if shape == "wrapper":
        agents = wrapper_config(script=f"cld() {{ {record}; }}")
        leading = []
    else:
        agents = AgentsConfig()
        leading = ["--dangerously-skip-permissions"]
    command = render(tmp_path, agents, PATH_ARGS["restart-respawn-recreate-reopen"])
    subprocess.run(command, shell=True, check=True, timeout=30,
                   env={"HOME": str(tmp_path), "PATH": f"{fake_bin}:/usr/bin:/bin"})
    argv = marker.read_text().splitlines()
    assert argv == leading + [f"--mcp-config={shared_on_disk}", "--resume", UUID, "--name", "Spike"]


@pytest.mark.parametrize("family", ["codex", "shell", "hermes", "openclaw", "local"])
def test_no_other_family_gets_the_flag(tmp_path, shared_on_disk, family):
    command = render(tmp_path, AgentsConfig(), ["--x"], agent_type=family, model="m")
    assert "--mcp-config" not in command


@pytest.mark.parametrize("content", [None, "not json", "{}", '{"mcpServers": []}'])
def test_a_missing_or_unusable_file_adds_no_flag(tmp_path, monkeypatch, content):
    """claude exits at once on a missing or invalid --mcp-config file (measured)."""
    path = tmp_path / "carnivore-mcp.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setenv(shared_mcp.SHARED_MCP_PATH_ENV_VAR, str(path))
    assert shared_mcp.mcp_config_args() == []
    assert "--mcp-config" not in render(tmp_path, wrapper_config(), None)


def test_every_launch_is_rendered_by_the_one_choke_point():
    pattern = re.compile(r"\b(resolve_launch|render_wrapper_invocation|agent_command)\(")
    callers = set()
    for path in (ROOT / "src").rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if pattern.search(stripped) and not stripped.startswith(("def ", "#", "Example", ">>>")) \
                    and "``" not in stripped and not stripped.startswith(("Description", "Output")):
                callers.add((path.relative_to(ROOT).as_posix(), pattern.search(stripped).group(1)))
    assert ("src/config/agent_command.py", "resolve_launch") in callers
    assert ("src/config/settings.py", "agent_command") in callers
    renderers = {c for c in callers if c[1] != "agent_command"}
    assert renderers == {
        ("src/config/agent_command.py", "resolve_launch"),
        ("src/api/launch_profiles_routes.py", "resolve_launch"),
    }
    assert 'resolve_launch(request, "preview")' in (
        ROOT / "src/api/launch_profiles_routes.py"
    ).read_text()




def test_migration_moves_only_the_copied_entries_and_keeps_profile_unique_ones(config, home):
    default_before = (home / ".claude.json").read_bytes()
    default_stamp = (home / ".claude.json").stat().st_mtime_ns
    assert set(converge(config).values()) == {profile_setup.WROTE}
    assert shared_file() == {"mcpServers": {"alpha": ALPHA, SECRET_NAME: BILLING}}
    assert profile("one")["mcpServers"] == {UNIQUE_NAME: MINE}
    assert profile("two")["mcpServers"] == {"alpha": {**ALPHA, "args": ["alpha", "--mine"]}}
    record = json.loads(shared_mcp.record_path().read_text())
    assert record["profiles"] == {"one": {"kept": [UNIQUE_NAME]}, "two": {"kept": ["alpha"]}}
    assert (home / ".claude.json").read_bytes() == default_before
    assert (home / ".claude.json").stat().st_mtime_ns == default_stamp
    assert set(converge(config).values()) == {profile_setup.CONVERGED}
    assert UNIQUE_NAME not in shared_file()["mcpServers"]
    assert profile("one")["mcpServers"] == {UNIQUE_NAME: MINE}


def test_a_server_added_in_a_profile_moves_to_the_shared_file(config):
    converge(config)
    path = Path(managed_dir_for("two")) / ".claude.json"
    document = json.loads(path.read_text())
    document["mcpServers"]["added"] = ADDED
    path.write_text(json.dumps(document))
    assert converge(config)["two"] == profile_setup.WROTE
    assert shared_file()["mcpServers"]["added"] == ADDED
    assert "added" not in profile("two")["mcpServers"]
    assert profile("two")["mcpServers"] == {"alpha": {**ALPHA, "args": ["alpha", "--mine"]}}
    assert profile("one")["mcpServers"] == {UNIQUE_NAME: MINE}


def test_a_server_added_to_the_default_login_is_copied_and_the_default_untouched(config, home):
    converge(config)
    default = json.loads((home / ".claude.json").read_text())
    default["mcpServers"]["added"] = ADDED
    (home / ".claude.json").write_text(json.dumps(default))
    before = (home / ".claude.json").read_bytes()
    converge(config)
    assert shared_file()["mcpServers"]["added"] == ADDED
    assert (home / ".claude.json").read_bytes() == before


def test_a_name_the_shared_file_holds_is_never_overwritten_or_destroyed(config):
    converge(config)
    path = Path(managed_dir_for("one")) / ".claude.json"
    document = json.loads(path.read_text())
    document["mcpServers"]["alpha"] = {**ALPHA, "args": ["alpha", "v2"]}
    path.write_text(json.dumps(document))
    converge(config)
    assert shared_file()["mcpServers"]["alpha"] == ALPHA
    assert profile("one")["mcpServers"]["alpha"] == {**ALPHA, "args": ["alpha", "v2"]}


def test_each_server_is_defined_once_per_launch_after_convergence(config, home):
    converge(config)
    shared = shared_file()["mcpServers"]
    record = json.loads(shared_mcp.record_path().read_text())["profiles"]
    for account_id in ("one", "two"):
        own = profile(account_id)["mcpServers"]
        assert set(own) & set(shared) <= set(record[account_id]["kept"])
        assert all(not shared_mcp.is_copy(n, e, shared) for n, e in own.items())
    assert set(json.loads((home / ".claude.json").read_text())["mcpServers"]) <= set(shared)


def test_a_profile_is_not_stripped_before_it_is_recorded(config, monkeypatch):
    monkeypatch.setattr(shared_mcp, "_read_record", lambda path: {})
    converge(config)
    assert set(profile("one")["mcpServers"]) == {"alpha", SECRET_NAME, UNIQUE_NAME}


def test_the_shared_file_the_record_and_the_profiles_stay_0600(config):
    old = os.umask(0o022)
    try:
        converge(config)
    finally:
        os.umask(old)
    assert mode_of(shared_mcp.shared_mcp_path()) == 0o600
    assert mode_of(shared_mcp.record_path()) == 0o600
    for account_id in ("one", "two"):
        assert mode_of(Path(managed_dir_for(account_id)) / ".claude.json") == 0o600
    path = Path(managed_dir_for("two")) / ".claude.json"
    document = json.loads(path.read_text())
    document["mcpServers"]["added"] = ADDED
    path.write_text(json.dumps(document))
    converge(config)
    assert mode_of(shared_mcp.shared_mcp_path()) == 0o600
    assert mode_of(shared_mcp.shared_mcp_path().with_suffix(".json.bak")) == 0o600


def test_no_server_name_value_or_project_path_is_ever_logged(config):
    with capture_logs() as logs:
        converge(config)
        path = Path(managed_dir_for("two")) / ".claude.json"
        document = json.loads(path.read_text())
        document["mcpServers"]["added"] = ADDED
        path.write_text(json.dumps(document))
        converge(config)
    events = {entry["event"] for entry in logs}
    assert {"provider_profile_converged", "shared_mcp_synced", "shared_mcp_profiles_migrated"} <= events
    text = repr(logs)
    for secret in (SECRET_VALUE, SECRET_NAME, UNIQUE_NAME, SECRET_PROJECT, "example.invalid"):
        assert secret not in text




def test_trust_is_copied_add_only_and_the_default_is_never_written(config, home):
    before = (home / ".claude.json").read_bytes()
    converge(config)
    projects = profile("one")["projects"]
    assert projects["/w/trusted"] == {"hasTrustDialogAccepted": True}
    assert projects[SECRET_PROJECT] == {"hasTrustDialogAccepted": True}
    assert projects["/w/flip"] == {"hasTrustDialogAccepted": True, "allowedTools": ["x"]}
    assert projects["/w/own"] == {"hasTrustDialogAccepted": True}
    assert projects["/w/own-false"] == {"hasTrustDialogAccepted": False}
    assert "/w/untrusted" not in projects
    assert set(profile("two")["projects"]) == {"/w/trusted", "/w/flip", SECRET_PROJECT}
    assert (home / ".claude.json").read_bytes() == before


def test_trust_survives_a_running_claudes_rewrite(config):
    converge(config)
    path = Path(managed_dir_for("one")) / ".claude.json"
    fresh = json.loads(path.read_text())
    fresh["numStartups"] = 7
    fresh["projects"]["/w/trusted"]["lastSessionId"] = "s-1"
    path.write_text(json.dumps(fresh))
    assert converge(config)["one"] == profile_setup.CONVERGED
    assert profile("one")["projects"]["/w/trusted"]["hasTrustDialogAccepted"] is True
    stale = {k: v for k, v in profile("one").items() if k != "projects"}
    path.write_text(json.dumps(stale))
    assert converge(config)["one"] == profile_setup.WROTE
    assert profile("one")["projects"]["/w/trusted"] == {"hasTrustDialogAccepted": True}



STUB = '''import json, os, sys
tag, log = sys.argv[1], sys.argv[2]
open(log, "a").write(f"{tag}\\n")
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("id") is None:
        continue
    method = msg.get("method")
    result = {}
    if method == "initialize":
        result = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": tag, "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "t_" + tag, "description": tag,
                             "inputSchema": {"type": "object", "properties": {}}}]}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
    sys.stdout.flush()
'''


def _claude_init(binary: str, env: dict, args: list, cwd: Path) -> dict:
    process = subprocess.Popen([binary, *args, "-p", "hi", "--output-format", "stream-json", "--verbose"],
                               cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    lines: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True).start()
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            if '"subtype":"init"' in line.replace(" ", ""):
                return json.loads(line)
        return {}
    finally:
        process.kill()
        process.wait(timeout=10)


@pytest.mark.skipif(shutil.which("claude") is None, reason="no claude binary installed")
def test_a_real_claude_starts_each_shared_server_once(config, home, tmp_path):
    starts = tmp_path / "starts.log"
    stub = tmp_path / "stub_mcp.py"
    stub.write_text(STUB)

    def server(tag):
        return {"type": "stdio", "command": sys.executable, "args": [str(stub), tag, str(starts)], "env": {}}

    default = {**DEFAULT_LOGIN, "mcpServers": {"alpha": server("alpha"), SECRET_NAME: server("billing")}}
    (home / ".claude.json").write_text(json.dumps(default))
    write_claude_profile(managed_dir_for("one"), extra={
        "mcpServers": {"alpha": server("alpha"), UNIQUE_NAME: server("mine")}})
    converge(config)
    work = tmp_path / "work"
    work.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb",
           "ANTHROPIC_API_KEY": "dummy-key-not-a-credential", "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",
           "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1"}
    flag = shared_mcp.mcp_config_args()
    assert flag == [f"--mcp-config={shared_mcp.shared_mcp_path()}"]
    binary = shutil.which("claude")

    default_copy = tmp_path / "default-login"
    default_copy.mkdir()
    (default_copy / ".claude.json").write_text((home / ".claude.json").read_text())
    for launch_env, wanted in (
        ({**env, "CLAUDE_CONFIG_DIR": str(default_copy)}, {"alpha": 1, "billing": 1}),
        ({**env, "CLAUDE_CONFIG_DIR": managed_dir_for("one")}, {"alpha": 1, "billing": 1, "mine": 1}),
    ):
        starts.write_text("")
        init = _claude_init(binary, launch_env, flag, work)
        names = [s["name"] for s in init.get("mcp_servers", [])]
        counted = {}
        for tag in starts.read_text().split():
            counted[tag] = counted.get(tag, 0) + 1
        assert counted == wanted
        assert sorted(names) == sorted(set(names)) and len(names) == len(wanted)




def test_the_second_stop_refuses_the_real_shared_file(second_stop, home):
    real = Path(REAL_HOME) / ".claude" / f"carnivore-mcp-never-{os.getpid()}-{time.time_ns()}.json"
    assert not str(real).startswith(str(home)) and not real.exists()
    with pytest.raises(AssertionError):
        config_writer.create_if_absent(real, {"never": "written"}, file_mode=0o600)
    assert len(second_stop) == 1 and Path(second_stop[0]).parent == real.parent
    assert not real.exists() and not Path(second_stop[0]).exists()
    second_stop.clear()
