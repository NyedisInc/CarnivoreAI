
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from src.core.json_artifact import UnreadableArtifact, read_for_update
from src.plugins.host import identity, sideload
from src.plugins.runtime.children import ChildLedger

UUID = "a" * 32
TORN = b'{"installs": {"clock": {"uuid": "aaa'


def _store_dir(state_dir: Path) -> Path:
    folder = state_dir / "cplugs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _ledger_write(state_dir: Path) -> None:
    identity.register_install(state_dir, "clock", "acme/clock", ())


def _sideload_switch(state_dir: Path) -> None:
    sideload.set_switch(state_dir, True)


def _sideload_forget(state_dir: Path) -> None:
    sideload.forget(state_dir, "clock")


def _sideload_put(state_dir: Path) -> None:
    sideload.put_install(state_dir, {"kind": "theme", "name": "dusk"})


def _children_forget(state_dir: Path) -> None:
    ChildLedger(state_dir).forget("clock")


CASES = {
    "installs-register": (identity.LEDGER_FILE, _ledger_write, (identity.LedgerUnreadable,)),
    "sideload-switch": (sideload.FILE_NAME, _sideload_switch, (sideload.SideloadRefused,)),
    "sideload-forget": (sideload.FILE_NAME, _sideload_forget, (sideload.SideloadRefused,)),
    "sideload-put": (sideload.FILE_NAME, _sideload_put, (sideload.SideloadRefused,)),
    "children-forget": ("children.json", _children_forget, ()),
}


@pytest.mark.parametrize("content", [TORN, b"[1, 2]", b"\xff\xfe\x00"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_writer_leaves_an_unreadable_store_alone(tmp_path: Path, case: str, content: bytes) -> None:
    name, writer, errors = CASES[case]
    path = _store_dir(tmp_path) / name
    path.write_bytes(content)
    sideload._snapshots.clear()
    if errors:
        with pytest.raises(errors):
            writer(tmp_path)
    else:
        writer(tmp_path)
    assert path.read_bytes() == content


def test_child_record_is_refused_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.automations import lifecycle

    monkeypatch.setattr(lifecycle, "describe_child", lambda pid: {"pid": pid, "start": "x"})
    path = _store_dir(tmp_path) / "children.json"
    path.write_bytes(TORN)
    assert ChildLedger(tmp_path).record("clock", 1234) is False
    assert path.read_bytes() == TORN


def test_child_reap_does_not_clear_an_unreadable_ledger(tmp_path: Path) -> None:
    path = _store_dir(tmp_path) / "children.json"
    path.write_bytes(TORN)
    assert ChildLedger(tmp_path).reap() == {}
    assert path.read_bytes() == TORN


def test_sideload_readers_still_default(tmp_path: Path) -> None:
    (_store_dir(tmp_path) / sideload.FILE_NAME).write_bytes(TORN)
    sideload._snapshots.clear()
    assert sideload.items(tmp_path) == {} and sideload.installs(tmp_path) == {}
    assert sideload.is_on(tmp_path) is False


def test_helper_contract(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    assert read_for_update(path, log_event="e") == {}
    path.write_text('{"a": 1}')
    assert read_for_update(path, log_event="e") == {"a": 1}
    path.write_text("nope")
    with pytest.raises(UnreadableArtifact):
        read_for_update(path, log_event="e")
