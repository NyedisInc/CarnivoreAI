
from __future__ import annotations

import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.argent import settings as argent_settings
from src.core.budget_hold import gate
from src.core.budget_hold.store import HoldStore
from src.core.launch_profiles import create_seam
from src.core.sessions import launch_overlay
from src.core.tmux_backend import TmuxBackend
from tests.argent.test_argent_launch_overlay import CA, GATEWAY, KEY, SECRET_NAME, ctx, launch, on, run  # noqa: F401
from tests.argent.test_argent_rollout import Manager, TENANT, _tether, env, info  # noqa: F401

pytestmark = pytest.mark.real_tmux


def argv_leaks(ps_snapshot: str) -> bool:
    return KEY in ps_snapshot


def pane_run(sock: str, tmp: Path, command: str, tag: str) -> dict:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    out, ps_out = tmp / f"{tag}.env", tmp / f"{tag}.ps"
    claude = bindir / "claude"
    claude.write_text(f'#!/bin/sh\n{{ echo "BASE=${{ANTHROPIC_BASE_URL-unset}}"; echo "HDR=${{ANTHROPIC_CUSTOM_HEADERS-unset}}"; '
                      f'echo "CA=${{NODE_EXTRA_CA_CERTS-unset}}"; echo "KEYVAR=${{{SECRET_NAME}-unset}}"; }} > "{out}.tmp"\n'
                      f'ps -axo args > "{ps_out}"; mv "{out}.tmp" "{out}"\n')
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    script = tmp / f"{tag}.sh"
    script.write_text(command + "\n")
    base = {"PATH": f"{bindir}:/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(tmp), "ZDOTDIR": str(tmp), "TERM": "xterm"}
    subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", "new-session", "-d", "-s", tag, f"sh {script}"], env=base, check=True, timeout=20)
    return base | {"_out": str(out), "_ps": str(ps_out)}


def wait_for(path: str, seconds: float = 20.0) -> str:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if Path(path).exists():
            return Path(path).read_text()
        time.sleep(0.2)
    raise AssertionError(f"pane never produced {path}")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_switch_on_then_off_in_a_real_pane_on_a_throwaway_socket(on, tmp_path, tmux_test_socket):  # noqa: F811
    sock = tmux_test_socket
    assert sock != "cloude"
    try:
        plan = launch(tmp_path)
        assert SECRET_NAME in plan.command and KEY not in plan.command
        prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
        assert prepared.late == {SECRET_NAME: KEY}
        handle = pane_run(sock, tmp_path, plan.command, "carnivore_on")
        backend = TmuxBackend.for_external(session_name="carnivore_on", working_dir=tmp_path, on_output=None, socket_name=sock)
        run(create_seam.deliver_late(backend, prepared))
        seen = dict(line.split("=", 1) for line in wait_for(handle["_out"]).splitlines())
        assert seen == {"BASE": GATEWAY, "HDR": f"x-api-key: {KEY}", "CA": CA, "KEYVAR": "unset"}
        snapshot = Path(handle["_ps"]).read_text()
        assert not argv_leaks(snapshot)
        assert argv_leaks(snapshot + f"\nclaude --key {KEY}")
        env_left = subprocess.run(["tmux", "-L", sock, "show-environment", "-t", "=carnivore_on"], capture_output=True, text=True, timeout=10).stdout
        assert SECRET_NAME not in env_left and KEY not in env_left

        on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, ca_path=CA, enabled=False)
        off_plan = launch(tmp_path)
        assert off_plan.overlay is None and SECRET_NAME not in off_plan.command
        handle = pane_run(sock, tmp_path, off_plan.command, "carnivore_off")
        seen = dict(line.split("=", 1) for line in wait_for(handle["_out"]).splitlines())
        assert seen == {"BASE": "unset", "HDR": "unset", "CA": "unset", "KEYVAR": "unset"}
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=10)


def test_rollout_plan_and_hold_gate_with_the_switch_on_then_off(env, tmp_path, monkeypatch):  # noqa: F811
    rows = [info("fresh"), info("busy", subagents_running=2), info("adopt", session=SimpleNamespace(id="adopted:adopt", working_dir="/w")), info("on")]
    _tether("on", True)
    from src.core.argent import rollout_preview
    plan = run(rollout_preview.preview(Manager(tmp_path, rows), TENANT, "on"))
    assert (plan["total"], plan["will_restart"], plan["adopted"], plan["subagents"]) == (4, 3, 1, 2)
    off = run(rollout_preview.preview(Manager(tmp_path, rows), TENANT, "off"))
    assert off["will_restart"] == 1

    store = HoldStore(tmp_path / "argent.db")
    monkeypatch.setattr(gate, "STORE", store)
    monkeypatch.setattr(gate, "switch_on", lambda: True)
    assert gate.hold_check(7, "\r", "idle", "ready").held is False
    store.set_hold("wi_1", "checkout rewrite", ["7"])
    assert gate.hold_check(7, "\r", "idle", "ready").held is True
    assert gate.hold_check(7, "\x1b", "idle", "ready").held is False
    assert gate.hold_check(8, "\r", "idle", "ready").held is False
    monkeypatch.setattr(gate, "switch_on", lambda: False)
    assert gate.hold_check(7, "\r", "idle", "ready").held is False


def test_argent_copy_never_says_plugin():
    root = Path(__file__).resolve().parents[2]
    docs = (root / "docs" / "argent.md").read_text()
    tools = (root / "src" / "core" / "mcp" / "argent_tools.py").read_text()
    catalog = [ln for ln in (root / "client/js/i18n/catalog.en.js").read_text().splitlines() if "argent." in ln]
    assert catalog, "no argent keys found"
    for name, text in (("docs/argent.md", docs), ("argent_tools.py", tools), ("catalog", "\n".join(catalog))):
        words = re.sub(r"[\w./-]*plugins/[\w./-]*", "", text)
        assert not re.search(r"plugin", words, re.I), f"the word plugin appears in {name}"
    with pytest.raises(AssertionError):
        assert not re.search(r"plugin", "a plugin", re.I)
