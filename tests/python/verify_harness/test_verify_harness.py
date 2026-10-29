
from __future__ import annotations

import json
import types
from typing import Any

import pytest

from scripts.lib import verify_harness as vh

BASE = "http://127.0.0.1:9999"


def _state(tmp_path, token: str | None = "tok", origin: str = BASE) -> str:
    items = [] if token is None else [{"name": "claude_tunnel_token", "value": token}]
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"origins": [{"origin": origin, "localStorage": items}]}))
    return str(path)


def test_token_of_reads_the_token_for_the_base_origin(tmp_path) -> None:
    assert vh.token_of(_state(tmp_path), BASE) == "tok"


def test_token_of_raises_when_origin_or_token_is_missing(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        vh.token_of(_state(tmp_path, origin="http://other"), BASE)
    with pytest.raises(RuntimeError):
        vh.token_of(_state(tmp_path, token=None), BASE)


def test_call_sends_bearer_json_and_decodes_the_answer(tmp_path, monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class _Answer:
        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, method=req.get_method(), auth=req.get_header("Authorization"),
                    body=req.data, timeout=timeout)
        return _Answer()

    monkeypatch.setattr(vh.urllib.request, "urlopen", fake_urlopen)
    args = types.SimpleNamespace(base=BASE, storage_state=_state(tmp_path))
    assert vh.call(args, "/x", "POST", {"a": 1}) == {"ok": True}
    assert seen["url"] == BASE + "/api/v1/x" and seen["method"] == "POST"
    assert seen["auth"] == "Bearer tok" and json.loads(seen["body"]) == {"a": 1}


def test_set_theme_patches_with_the_current_revision(monkeypatch) -> None:
    sent: list[tuple] = []

    def fake_call(args, path, method="GET", body=None):
        sent.append((path, method, body))
        return {"revision": 7}

    monkeypatch.setattr(vh, "call", fake_call)
    vh.set_theme(object(), "dracula")
    assert sent[-1] == ("/preferences", "PATCH", {"changes": {"theme": "dracula"}, "expected_revision": 7})


def test_guarded_records_a_raise_as_a_failed_check_and_names_the_running_check() -> None:
    class _Report:
        calls: list[tuple] = []

        def check(self, ok, name, detail=""):
            self.calls.append((ok, name, detail))

    report, current = _Report(), {}

    def boom() -> None:
        raise ValueError("nope")

    vh.guarded(report, "step", boom, current)
    assert current == {"check": "step"}
    assert report.calls == [(False, "step: the check could not run to the end", "ValueError: nope")]
    report.calls.clear()
    vh.guarded(report, "fine", lambda: None)
    assert report.calls == []


def test_check_prints_and_collects_only_failures(capsys) -> None:
    failures: list[str] = []
    vh.check(True, "good", failures)
    vh.check(False, "bad", failures)
    assert capsys.readouterr().out == "PASS good\nFAIL bad\n"
    assert failures == ["bad"]


def test_dismiss_offers_clicks_when_visible_and_swallows_when_absent() -> None:
    log: list[str] = []

    class _Locator:
        def __init__(self, visible: bool) -> None:
            self.visible = visible

        def wait_for(self, state, timeout):
            if not self.visible:
                raise TimeoutError("not shown")

        def click(self) -> None:
            log.append("click")

    class _Page:
        def __init__(self, visible: bool) -> None:
            self.visible = visible

        def locator(self, sel):
            assert sel == "#restore-offer-no"
            return _Locator(self.visible)

        def wait_for_timeout(self, ms) -> None:
            log.append(f"wait{ms}")

    vh.dismiss_offers(_Page(True))
    assert log == ["click", "wait300"]
    log.clear()
    vh.dismiss_offers(_Page(False))
    assert log == []


def test_tmux_runs_on_the_given_socket_and_returns_stdout(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv, **kw):
        seen.update(argv=argv, kw=kw)
        return types.SimpleNamespace(stdout="out")

    monkeypatch.setattr(vh.subprocess, "run", fake_run)
    assert vh.tmux("sock", "list-sessions") == "out"
    assert seen["argv"] == ["tmux", "-L", "sock", "list-sessions"] and seen["kw"]["check"] is False
