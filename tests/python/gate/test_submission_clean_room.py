
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from scripts.warez_gates import clean_room
from src.core.mods.inventory import MIN_CLAUDE_VERSION
from tests.helpers.clean_room_kits import GATE_KINDS, gate_world, keys  # noqa: F401
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.mods.test_mod_install_gates import WORKING_ON, fake_claude

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

NO_CSS_VARS = {"theme.json": json.dumps({"id": "probe_theme", "name": "Probe Theme", "description": "d", "author": "carnivore",
                                           "version": "1.0.0", "xterm": {"background": "#101014"}}).encode()}
STAND_IN_NETNS = ["env"]


def pinned_claude(base: Path) -> str:
    inner = fake_claude(base, WORKING_ON)
    wrapper = base / "claude-pinned"
    wrapper.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "{clean_room.CLAUDE_CODE_VERSION} (Claude Code)"; exit 0; fi\nexec "{inner}" "$@"\n')
    wrapper.chmod(0o755)
    return str(wrapper)


def _gate(kind: str, base: Path, keys, monkeypatch, *, plant: bool = False, files: Optional[dict] = None,
          netns: Optional[list] = STAND_IN_NETNS):
    (base / "served").mkdir(parents=True)
    claude = pinned_claude(base)
    with gate_world(kind, base, base / "served", keys, monkeypatch, plant=plant, theme_files=files) as (item, host, item_id, residue):
        return clean_room.run(item, host, item_id, claude=claude, netns=netns, residue=residue)


@pytest.mark.parametrize("kind", GATE_KINDS)
def test_gate_11_passes_a_good_folder_and_fails_a_bad_one(kind: str, tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    good = _gate(kind, tmp_path / "good", keys, monkeypatch)
    assert (good.verdict, good.code) == ("pass", "ok"), (good.verdict, good.code, [f.code for f in good.findings])

    bad = _gate(kind, tmp_path / "bad", keys, monkeypatch, plant=True)
    assert bad.verdict == "fail" and "residue_left" in {f.code for f in bad.findings}, (bad.verdict, bad.code)


def test_a_theme_without_css_vars_fails_the_use_step(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _gate("theme", tmp_path, keys, monkeypatch, files=NO_CSS_VARS)
    assert result.verdict == "fail" and result.code == "use_failed", (result.verdict, result.code)


def test_author_code_without_a_network_namespace_is_undetermined(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    ran = tmp_path / "ran"
    monkeypatch.setattr(clean_room.subprocess, "run", _spy(clean_room.subprocess.run, ran))
    result = _gate("mod", tmp_path, keys, monkeypatch, netns=None)
    assert (result.verdict, result.code) == ("undetermined", "no_network_namespace"), (result.verdict, result.code)
    assert "plugin test" not in ran.read_text(encoding="utf-8") if ran.exists() else True, "author code ran without a namespace"


def test_the_pinned_claude_meets_the_mod_floor() -> None:
    assert tuple(int(p) for p in clean_room.CLAUDE_CODE_VERSION.split(".")) >= MIN_CLAUDE_VERSION
    assert clean_room.CLAUDE_CODE_NPM_SPEC.endswith("@" + clean_room.CLAUDE_CODE_VERSION)


def _spy(real, log: Path):
    def spy(cmd, *args, **kwargs):
        with log.open("a", encoding="utf-8") as handle:
            handle.write(" ".join(str(c) for c in cmd) + "\n")
        return real(cmd, *args, **kwargs)
    return spy


def _recorded(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch, netns: list) -> tuple:
    seen: list = []
    real = clean_room.subprocess.run

    def spy(cmd, *args, **kwargs):
        seen.append([str(c) for c in cmd])
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(clean_room.subprocess, "run", spy)
    return _gate("mod", tmp_path, keys, monkeypatch, netns=netns), seen


def test_author_code_argv_starts_with_the_namespace_prefix(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = ["env", "WAREZ_NETNS_MARK=1"]
    result, seen = _recorded(tmp_path, keys, monkeypatch, prefix)
    author = [a for a in seen if "plugin" in a and ("test" in a or "details" in a)]
    assert len(author) == 2, author
    assert all(a[:2] == prefix for a in author), author
    validate = [a for a in seen if "validate" in a]
    assert validate and all(a[:2] != prefix for a in validate), validate
    assert (result.verdict, result.code) == ("pass", "ok"), (result.verdict, result.code)


def test_an_empty_namespace_prefix_is_no_namespace(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _recorded(tmp_path, keys, monkeypatch, [])
    assert (result.verdict, result.code) == ("undetermined", "no_network_namespace"), (result.verdict, result.code)
    assert not [a for a in seen if "test" in a or "details" in a], seen


def test_a_missing_residue_probe_is_undetermined_never_a_pass(tmp_path: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "served").mkdir()
    claude = pinned_claude(tmp_path)
    with gate_world("skill", tmp_path, tmp_path / "served", keys, monkeypatch, plant=False, theme_files=None) as (item, host, item_id, _):
        result = clean_room.run(item, host, item_id, claude=claude, netns=STAND_IN_NETNS)
    assert (result.verdict, result.code) == ("undetermined", "residue_probe_missing"), (result.verdict, result.code)


def _done(code: int):
    def fake(cmd, **kwargs):
        fake.argv = list(cmd)
        return subprocess.CompletedProcess(cmd, code)
    fake.argv = None
    return fake


def test_netns_prefix_is_the_unshare_command_only_when_a_probe_runs_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean_room.shutil, "which", lambda name: "/usr/bin/unshare")
    ok = _done(0)
    assert clean_room.netns_prefix(ok) == ["/usr/bin/unshare", "-rn"]
    assert ok.argv == ["/usr/bin/unshare", "-rn", "true"]
    assert clean_room.netns_prefix(_done(1)) is None

    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)

    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    assert clean_room.netns_prefix(timeout) is None and clean_room.netns_prefix(missing) is None
    monkeypatch.setattr(clean_room.shutil, "which", lambda name: None)
    assert clean_room.netns_prefix(ok) is None
