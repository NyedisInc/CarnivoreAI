
from __future__ import annotations

import builtins
import io
import json
import os
from pathlib import Path
from typing import Any, Callable, List

import pytest

from src.core.backup_health import vault_record
from src.cplugs.save.vault.location import open_root
from src.cplugs.save.vault.manifest import ManifestStore
from src.cplugs.sdk import dir_listing

OLD_NS = 10 * dir_listing.TRUST_AFTER_NS


def _count_opens(monkeypatch: pytest.MonkeyPatch, target: Path) -> List[str]:
    seen: List[str] = []

    def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
        def counting(file: Any, *args: Any, **kwargs: Any) -> Any:
            if str(file) == str(target):
                seen.append(str(file))
            return real(file, *args, **kwargs)
        return counting

    monkeypatch.setattr(builtins, "open", wrap(builtins.open))
    monkeypatch.setattr(io, "open", wrap(io.open))
    return seen


def _write_config(path: Path, location: str) -> None:
    path.write_text(json.dumps({"save_pipeline": {"vault_location": location}}), encoding="utf-8")


def test_changed_config_is_seen_on_the_next_call(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    _write_config(config, "/Volumes/A/vault")
    assert vault_record.location_of(vault_record.read_config(config)) == "/Volumes/A/vault"
    _write_config(config, "/Volumes/B/vault")
    assert vault_record.location_of(vault_record.read_config(config)) == "/Volumes/B/vault"
    config.unlink()
    assert vault_record.read_config(config) == {}


def test_unchanged_config_is_not_opened_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.json"
    _write_config(config, "")
    opens = _count_opens(monkeypatch, config)
    first = vault_record.read_config(config)
    second = vault_record.read_config(config)
    assert first == second
    assert len(opens) == 1


def test_open_root_reads_the_config_once_across_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, state = tmp_path / "config.json", tmp_path / "state"
    state.mkdir()
    _write_config(config, "")
    opens = _count_opens(monkeypatch, config)
    roots = {open_root(state, config) for _ in range(5)}
    assert roots == {state / "vault"}
    assert len(opens) <= 1


def test_unreadable_config_is_not_kept(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{not json", encoding="utf-8")
    assert vault_record.read_config(config) == {}
    _write_config(config, "/Volumes/A/vault")
    assert vault_record.location_of(vault_record.read_config(config)) == "/Volumes/A/vault"


def _unit(store_root: Path, name: str, ids: List[str]) -> Path:
    folder = store_root / "manifests" / name
    folder.mkdir(parents=True, exist_ok=True)
    for point in ids:
        (folder / f"{point}.json").write_text("{}", encoding="utf-8")
    return folder


def _age(folder: Path, ns: int) -> None:
    os.utime(folder, ns=(ns, ns))


def test_new_point_in_a_manifest_folder_is_picked_up(tmp_path: Path) -> None:
    folder = _unit(tmp_path, "conv-aaa", ["20260101T000000Z"])
    _age(folder, 1_000_000_000)
    store = ManifestStore(tmp_path)
    assert store.point_ids("conv-aaa") == ["20260101T000000Z"]
    (folder / "20260102T000000Z.json").write_text("{}", encoding="utf-8")
    _age(folder, 2_000_000_000)
    assert store.point_ids("conv-aaa") == ["20260101T000000Z", "20260102T000000Z"]
    (folder / "20260101T000000Z.json").unlink()
    _age(folder, 3_000_000_000)
    assert store.point_ids("conv-aaa") == ["20260102T000000Z"]


def test_new_point_is_picked_up_even_inside_the_trust_window(tmp_path: Path) -> None:
    folder = _unit(tmp_path, "conv-bbb", ["20260101T000000Z"])
    store = ManifestStore(tmp_path)
    assert store.point_ids("conv-bbb") == ["20260101T000000Z"]
    mtime = folder.stat().st_mtime_ns
    (folder / "20260102T000000Z.json").write_text("{}", encoding="utf-8")
    _age(folder, mtime)
    assert store.point_ids("conv-bbb") == ["20260101T000000Z", "20260102T000000Z"]


def test_unchanged_folder_is_not_listed_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = _unit(tmp_path, "conv-ccc", ["20260101T000000Z"])
    _age(folder, 1_000_000_000)
    store = ManifestStore(tmp_path)
    listed: List[Path] = []
    real = Path.iterdir

    def counting(self: Path) -> Any:
        if self == folder:
            listed.append(self)
        return real(self)

    monkeypatch.setattr(Path, "iterdir", counting)
    for _ in range(4):
        assert store.point_ids("conv-ccc") == ["20260101T000000Z"]
    assert len(listed) == 1


def test_absent_unit_is_empty_and_not_kept(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path)
    assert store.point_ids("conv-ddd") == []
    folder = _unit(tmp_path, "conv-ddd", ["20260101T000000Z"])
    _age(folder, OLD_NS)
    assert store.point_ids("conv-ddd") == ["20260101T000000Z"]


def test_cached_and_uncached_passes_agree(tmp_path: Path) -> None:
    units = [f"conv-{n:03d}" for n in range(25)]
    for name in units:
        _age(_unit(tmp_path, name, [f"2026010{d}T000000Z" for d in range(1, 4)]), 1_000_000_000)
    warm = ManifestStore(tmp_path)
    clock = 2_000_000_000
    for step in range(3):
        for name in units:
            assert warm.point_ids(name) == ManifestStore(tmp_path).point_ids(name)
        for name in units[::3]:
            folder = tmp_path / "manifests" / name
            (folder / f"2026020{step + 1}T000000Z.json").write_text("{}", encoding="utf-8")
            clock += 1_000_000_000
            _age(folder, clock)
    assert [warm.point_ids(n) for n in units] == [ManifestStore(tmp_path).point_ids(n) for n in units]
