from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.lib.testsrv_client import TestsrvTokenError, access_token  # noqa: E402


def _state(tmp_path: Path, origins: list[dict]) -> str:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"origins": origins}))
    return str(p)


def _origin(url: str, token: str | None) -> dict:
    items = [{"name": "other", "value": "x"}] + ([{"name": "claude_tunnel_token", "value": token}] if token else [])
    return {"origin": url, "localStorage": items}


def test_token_found_on_a_later_origin(tmp_path: Path) -> None:
    state = _state(tmp_path, [_origin("http://a", None), _origin("http://b", "tok-b")])
    assert access_token(state) == "tok-b"


def test_base_selects_its_own_origin(tmp_path: Path) -> None:
    state = _state(tmp_path, [_origin("http://a", "tok-a"), _origin("http://b", "tok-b")])
    assert access_token(state, "http://b") == "tok-b"


def test_missing_token_raises_the_named_error(tmp_path: Path) -> None:
    with pytest.raises(TestsrvTokenError):
        access_token(_state(tmp_path, [_origin("http://a", None)]))
