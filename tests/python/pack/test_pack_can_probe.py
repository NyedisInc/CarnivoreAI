
from __future__ import annotations

import json
import os
import plistlib
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.dev_tools import git_guard
from src.core.pack.machines import can_block, probe

APPLE_PROFILE = json.dumps({"SPDisplaysDataType": [{
    "_name": "Apple M1 Max", "spdisplays_mtlgpufamilysupport": "spdisplays_metal4", "spdisplays_vendor": "sppci_vendor_Apple",
    "sppci_bus": "spdisplays_builtin", "sppci_cores": "32", "sppci_device_type": "spdisplays_gpu", "sppci_model": "Apple M1 Max"}]})
AMD_PROFILE = json.dumps({"SPDisplaysDataType": [
    {"_name": "Intel UHD", "spdisplays_vendor": "sppci_vendor_Intel", "sppci_bus": "spdisplays_builtin", "sppci_model": "Intel UHD Graphics 630"},
    {"_name": "Radeon Pro 5500M", "spdisplays_vendor": "sppci_vendor_AMD", "sppci_bus": "spdisplays_pcie_device",
     "sppci_model": "AMD Radeon Pro 5500M", "spdisplays_vram": "8 GB"}]})
NVIDIA_4090 = "NVIDIA GeForce RTX 4090, 24564\n"
SPECS = {"arch": "arm64", "chip": "Apple M1 Max", "cores": 10, "mem_total_gb": 64.0}


class Runner:

    def __init__(self, answers: Dict[str, Optional[str]]) -> None:
        self.answers, self.calls = answers, []

    def __call__(self, argv: List[str]) -> Optional[str]:
        self.calls.append(list(argv))
        return self.answers.get(os.path.basename(argv[0]).removesuffix(".exe"))


def make_xcode(root: Path, version: str = "16.1") -> str:
    app = root / "Xcode.app" / "Contents"
    (app / "Developer").mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))
    return str(app / "Developer")


def run_all(tmp_path: Path, runner: Runner, system: str = "Darwin") -> Dict[str, Any]:
    return probe.run_probe(run=runner, system=system, home=tmp_path, specs=lambda: dict(SPECS), now=lambda: 1000.0,
                           apps_dir=tmp_path / "apps", sim_root=tmp_path / "sim")


def test_every_argv_is_from_the_fixed_set_and_no_forbidden_binary_runs(tmp_path: Path) -> None:
    runner = Runner({"xcode-select": make_xcode(tmp_path) + "\n", "system_profiler": APPLE_PROFILE})
    run_all(tmp_path, runner)
    assert runner.calls, "the runner was never called, so this check looked at nothing"
    assert {tuple(c) for c in runner.calls} <= set(probe.FIXED_ARGV)
    for name in ("xcodebuild", "xcrun", "simctl", "docker"):
        assert all(name not in c[0] for c in runner.calls)
    nv = Runner({"nvidia-smi": NVIDIA_4090})
    run_all(tmp_path, nv, "Linux")
    assert nv.calls == [list(probe.NVIDIA_SMI_ARGVS[0])]


def test_xcode_version_read_from_plist_and_clt_is_not_xcode(tmp_path: Path) -> None:
    dev = make_xcode(tmp_path, "16.1")
    runner = Runner({"xcode-select": dev + "\n"})
    assert probe.xcode_macos(runner, sim_root=tmp_path / "sim") == ("16.1", False)
    assert runner.calls == [probe.XCODE_SELECT_ARGV]
    clt = Runner({"xcode-select": "/Library/Developer/CommandLineTools\n"})
    assert probe.xcode_macos(clt, sim_root=tmp_path / "sim") == (None, False)
    assert clt.calls, "xcode-select was not asked"
    assert probe.xcode_macos(Runner({}), sim_root=tmp_path / "sim")[0] is None
    broken = tmp_path / "Bad.app" / "Contents" / "Developer"
    broken.mkdir(parents=True)
    assert probe.xcode_macos(Runner({"xcode-select": str(broken)}), sim_root=tmp_path / "sim")[0] is None


def test_ios_sim_found_in_the_real_volumes_layout_and_not_in_a_deep_decoy(tmp_path: Path) -> None:
    real = tmp_path / "sim" / "Volumes" / "iOS_23F77" / "Library" / "Developer" / "CoreSimulator" / "Profiles" / "Runtimes"
    (real / "iOS 26.5.simruntime").mkdir(parents=True)
    assert probe.xcode_macos(Runner({}), sim_root=tmp_path / "sim") == (None, True)
    decoy = tmp_path / "other" / "a" / "b" / "c" / "d.simruntime"
    decoy.mkdir(parents=True)
    assert probe.xcode_macos(Runner({}), sim_root=tmp_path / "other") == (None, False)


def test_a_plist_that_is_not_a_dict_or_not_xml_is_no_version_not_a_crash(tmp_path: Path) -> None:
    dev = make_xcode(tmp_path)
    plist = Path(dev).parent / "Info.plist"
    plist.write_bytes(plistlib.dumps(["not", "a", "dict"]))
    assert probe.xcode_macos(Runner({"xcode-select": dev}), sim_root=tmp_path / "sim")[0] is None
    plist.write_text("<?xml version='1.0'?><plist><dict>")
    assert probe.xcode_macos(Runner({"xcode-select": dev}), sim_root=tmp_path / "sim")[0] is None


def test_ios_sim_true_when_a_simruntime_folder_exists(tmp_path: Path) -> None:
    (tmp_path / "sim" / "Profiles" / "Runtimes" / "iOS 18.0.simruntime").mkdir(parents=True)
    assert probe.xcode_macos(Runner({}), sim_root=tmp_path / "sim") == (None, True)


def test_gpus_apple_amd_and_4090(tmp_path: Path) -> None:
    apple = probe.gpus(Runner({"system_profiler": APPLE_PROFILE}), "Darwin")
    assert apple == [{"vendor": "apple", "model": "Apple M1 Max", "vram_gb": None, "discrete": False}]
    amd = probe.gpus(Runner({"system_profiler": AMD_PROFILE}), "Darwin")
    assert [g["vendor"] for g in amd] == ["intel", "amd"]
    assert amd[1]["discrete"] is True and amd[1]["vram_gb"] == 8.0 and amd[0]["discrete"] is False
    four = Runner({"nvidia-smi": NVIDIA_4090})
    assert probe.gpus(four, "Linux") == [{"vendor": "nvidia", "model": "NVIDIA GeForce RTX 4090", "vram_gb": 24.0, "discrete": True}]
    assert four.calls == [list(probe.NVIDIA_SMI_ARGVS[0])]
    assert probe.gpus(Runner({"nvidia-smi": NVIDIA_4090 * 6}), "Windows").__len__() == probe.MAX_GPUS
    assert probe.gpus(Runner({"system_profiler": "not json"}), "Darwin") == []
    assert probe.gpus(Runner({}), "Linux") == []


def test_apple_shim_is_not_a_tool_and_a_real_one_in_an_extra_dir_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_guard.shutil, "which", lambda tool, path=None: "/usr/bin/" + tool)
    monkeypatch.setattr(git_guard, "_is_macos", lambda: True)
    monkeypatch.setattr(git_guard, "_developer_dirs_have", lambda tool, honor_developer_dir=True: False)
    assert probe.find_tools([], system="Darwin", apps_dir=tmp_path)["ffmpeg"] is False
    monkeypatch.undo()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert probe.find_tools([], system="Linux")["ffmpeg"] is False
    assert probe.find_tools([str(bin_dir)], system="Linux")["ffmpeg"] is True


def test_blender_app_counts_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "Blender.app").mkdir()
    assert probe.find_tools([], system="Darwin", apps_dir=tmp_path)["blender"] is True
    assert probe.find_tools([], system="Linux", apps_dir=tmp_path)["blender"] is False


def test_run_probe_shape_and_the_block_it_builds_parses(tmp_path: Path) -> None:
    runner = Runner({"xcode-select": make_xcode(tmp_path) + "\n", "system_profiler": APPLE_PROFILE})
    result = run_all(tmp_path, runner)
    assert (result["os"], result["arch"], result["cores"], result["mem_gb"], result["xcode"]) == ("macos", "arm64", 10, 64.0, "16.1")
    assert "playwright_browsers" in result["tools"] and result["probed_at"] == 1000.0
    cache = tmp_path / "Library" / "Caches" / "ms-playwright" / "chromium-1"
    cache.mkdir(parents=True)
    assert run_all(tmp_path, runner)["tools"]["playwright_browsers"] is True
    assert can_block.parse(can_block.build(result, ["rtx 4090"], None)) is not None


def test_hung_command_is_cut_at_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: List[Any] = []

    def hang(argv: List[str], **kw: Any) -> Any:
        seen.append((argv, kw["timeout"], kw["stdin"]))
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(probe.subprocess, "run", hang)
    assert probe._run(probe.XCODE_SELECT_ARGV) is None
    assert probe._run(probe.SYSTEM_PROFILER_ARGV) is None
    assert [s[1] for s in seen] == [5.0, 10.0] and all(s[2] == subprocess.DEVNULL for s in seen)


def test_budget_skips_commands_after_30_seconds(tmp_path: Path) -> None:
    ticks = iter([0.0, 100.0, 200.0, 300.0])
    runner = Runner({"xcode-select": make_xcode(tmp_path), "system_profiler": APPLE_PROFILE})
    result = probe.run_probe(run=runner, system="Darwin", home=tmp_path, specs=lambda: dict(SPECS), monotonic=lambda: next(ticks),
                             apps_dir=tmp_path / "apps", sim_root=tmp_path / "sim")
    assert runner.calls == [] and result["xcode"] is None and result["gpus"] == []


def fake_probe(at: float) -> Dict[str, Any]:
    return {"probed_at": at, "os": "linux", "tools": {"git": True}, "gpus": [], "xcode": None, "ios_sim": False, "brew": False}


def test_keeper_file_mode_atomic_rate_limit_and_due(tmp_path: Path) -> None:
    now = [10_000.0]
    calls: List[int] = []

    def counting() -> Dict[str, Any]:
        calls.append(1)
        return fake_probe(now[0])

    keeper = probe.CanKeeper(tmp_path, clock=lambda: now[0], labels=lambda: ["lab one"], probe=counting)
    assert keeper.current() == {} and keeper.due() is True
    block, fresh = keeper.refresh("boot")
    assert fresh and calls == [1] and block["labels"] == ["lab one"] and can_block.parse(block) is not None
    path = tmp_path / "pack" / "can.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and not list(path.parent.glob("*.tmp"))
    assert json.loads(path.read_text())["probed_at"] == 10_000.0
    now[0] += 30
    block2, fresh2 = keeper.refresh("rescan")
    assert fresh2 is False and calls == [1] and block2["rev"] == block["rev"]
    assert keeper.due() is False
    now[0] += 61
    assert keeper.due() is False, "fresh result under 24 h must not be due"
    now[0] += 24 * 3600
    assert keeper.due() is True
    assert keeper.refresh("daily")[1] is True and calls == [1, 1]
    again = probe.CanKeeper(tmp_path, clock=lambda: now[0], probe=counting)
    assert again.current()["os"] == "linux" and calls == [1, 1], "a restart must load the file, not re-probe"


def test_keeper_ignores_a_corrupt_file_and_validates_installing(tmp_path: Path) -> None:
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "can.json").write_text("{nope")
    keeper = probe.CanKeeper(tmp_path, clock=lambda: 1.0, probe=lambda: fake_probe(1.0))
    assert keeper.current() == {}
    keeper.refresh("boot")
    keeper.set_installing("ffmpeg")
    assert keeper.current()["installing"] == "ffmpeg"
    keeper.set_installing(None)
    assert keeper.current()["installing"] is None
    with pytest.raises(ValueError):
        keeper.set_installing("rm -rf")


def test_labels_change_shows_without_a_probe(tmp_path: Path) -> None:
    labels: List[str] = []
    keeper = probe.CanKeeper(tmp_path, clock=lambda: 5.0, labels=lambda: labels, probe=lambda: fake_probe(5.0))
    first = keeper.refresh("boot")[0]
    labels.append("render box")
    assert keeper.current()["rev"] != first["rev"]
