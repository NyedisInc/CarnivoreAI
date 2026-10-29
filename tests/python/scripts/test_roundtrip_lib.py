from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

LIB = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "roundtrip_lib"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, LIB / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_verdict_intact_when_old_reads_the_last_persisted_session() -> None:
    v = _load("meta_verdict")
    detach = {"persisted_after_detach": "roundtrip-b"}
    assert v.decide(detach, {"present": True, "session_id": "roundtrip-b"}, False, True)[0] == "INTACT"


@pytest.mark.parametrize("detach", [{"_unreadable": "x"}, {"error": "boom"}, {}])
def test_verdict_cannot_determine_when_the_detach_step_measured_no_id(detach: dict) -> None:
    assert _load("meta_verdict").decide(detach, {"present": True, "session_id": "b"}, False, True)[0] == "CANNOT-DETERMINE"


@pytest.mark.parametrize(
    "old_d, cleared, rehydrated, expected",
    [
        ({"_unreadable": "x"}, False, True, "CANNOT-DETERMINE"),
        ({"present": True}, None, None, "CANNOT-DETERMINE"),
        ({"present": True}, True, False, "CANNOT-DETERMINE"),
        ({"present": False, "resolved": "/x"}, False, True, "ABSENT"),
        ({"present": True, "session_id": "other"}, False, True, "STALE"),
    ],
)
def test_verdict_ladder(old_d: dict, cleared: object, rehydrated: object, expected: str) -> None:
    detach = {"persisted_after_detach": "roundtrip-b"}
    assert _load("meta_verdict").decide(detach, old_d, cleared, rehydrated)[0] == expected


def test_pin_socket_writes_the_throwaway_name(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    _load("pin_socket").pin_socket(cfg, "rt_1")
    assert json.loads(cfg.read_text())["session"]["tmux_socket_name"] == "rt_1"


def test_pin_socket_refuses_the_production_socket(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    with pytest.raises(SystemExit):
        _load("pin_socket").pin_socket(cfg, "cloude")
    assert cfg.read_text() == "{}"
