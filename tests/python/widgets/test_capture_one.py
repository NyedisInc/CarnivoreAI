
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.widgets import harness

NOTE = "/sessions/cloude_billing-api/note"
SCENARIO = {f"GET {NOTE}": {"status": "ok", "revision": 3, "body": "# from the box\n\nscenario marker text", "updated_at": "2026-10-18T00:00:00Z"}}
BASE_ARGS = ["--widget", "core.notes", "--host", "home", "--size", "m", "--theme", "carnivore"]


def run_capture(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    done = subprocess.run([sys.executable, "-m", "scripts.widgets.capture_one", "--no-build", "--out", str(tmp_path / "out"), *extra],
                          cwd=harness.REPO, capture_output=True, text=True, timeout=300)
    lines = done.stdout.strip().splitlines()
    return done.returncode, json.loads(lines[-1]) if lines else {}


def write_scenario(tmp_path: Path, body: Any, name: str = "scenario.json") -> str:
    path = tmp_path / name
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return str(path)


def png_dims(path: str) -> tuple[int, int]:
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data.endswith(b"IEND\xaeB`\x82")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@pytest.fixture(scope="module")
def built(page_and_base):
    return page_and_base


def test_a_normal_capture_writes_a_complete_png_and_its_metadata(built, tmp_path: Path) -> None:
    code, meta = run_capture(tmp_path, *BASE_ARGS)
    assert code == 0 and meta["ok"] is True, meta
    assert png_dims(meta["png"]["path"]) == (416, 288)
    assert meta["png"]["pixels"] == [416, 288]
    on_disk = json.loads(Path(meta["metadata"]).read_text())
    assert on_disk["widget"] == "core.notes" and on_disk["host"] == "home" and on_disk["theme"] == "carnivore" and on_disk["state"] == "normal"
    assert on_disk["size"] == {"name": "m", "w": 384, "h": 256, "viewport": 1600}
    assert len(on_disk["source_revision"]["sha"]) == 40 and isinstance(on_disk["source_revision"]["dirty"], bool)
    assert on_disk["fixture"]["kind"] == "data" and on_disk["fixture"]["scenario"] is False and len(on_disk["fixture"]["hash"]) == 64
    assert "retry policy" in on_disk["text"] and on_disk["failures"] == []


def test_a_menu_open_capture_includes_the_open_menu(built, tmp_path: Path) -> None:
    _, normal = run_capture(tmp_path, *BASE_ARGS)
    code, meta = run_capture(tmp_path, *BASE_ARGS, "--state", "menu")
    assert code == 0 and meta["ok"] is True and meta["menu_open"] is True, meta
    assert meta["state"] == "menu" and meta["png"]["path"] != normal["png"]["path"]
    width, height = png_dims(meta["png"]["path"])
    assert width >= 416 and height >= 288


def test_a_pasted_scenario_drives_the_widget_and_is_hashed(built, tmp_path: Path) -> None:
    _, baseline = run_capture(tmp_path, *BASE_ARGS)
    code, meta = run_capture(tmp_path, *BASE_ARGS, "--scenario-file", write_scenario(tmp_path, SCENARIO))
    assert code == 0 and meta["ok"] is True, meta
    assert "scenario marker text" in meta["text"] and "retry policy" not in meta["text"]
    assert meta["fixture"]["scenario"] is True and meta["fixture"]["hash"] != baseline["fixture"]["hash"]


@pytest.mark.parametrize(("name", "body", "words"), [
    ("not-json", '{"GET /x": ', "not valid json"),
    ("not-a-route", '{"sessions/list": []}', "is not a route"),
    ("empty", "{}", "no routes"),
    ("typo", {"GET /sessions/cloude_billing-api/nte": {"revision": 1}}, "never asked for it"),
])
def test_a_deliberately_broken_fixture_fails_the_same_runner_with_a_useful_report(built, tmp_path: Path, name: str, body: Any, words: str) -> None:
    code, meta = run_capture(tmp_path, *BASE_ARGS, "--scenario-file", write_scenario(tmp_path, body, f"{name}.json"))
    assert code == 1 and meta["ok"] is False, meta
    assert any(words in failure for failure in meta["failures"]), meta["failures"]
    assert json.loads(Path(meta["metadata"]).read_text())["ok"] is False


@pytest.mark.parametrize(("args", "words"), [
    (["--widget", "core.no-such", "--host", "home", "--size", "m", "--theme", "carnivore"], "no widget core.no-such"),
    (["--widget", "core.notes", "--host", "home", "--size", "huge", "--theme", "carnivore"], "no size huge"),
    (["--widget", "core.notes", "--host", "home", "--size", "glance", "--theme", "carnivore"], "no size glance"),
])
def test_a_missing_widget_or_size_is_a_failed_capture_never_a_pass(built, tmp_path: Path, args: list[str], words: str) -> None:
    code, meta = run_capture(tmp_path, *args)
    assert code == 1 and meta["ok"] is False and any(words in failure for failure in meta["failures"]), meta
    assert meta["png"]["pixels"] is None


def test_a_failed_capture_never_leaves_an_earlier_picture_standing(built, tmp_path: Path) -> None:
    code, good = run_capture(tmp_path, *BASE_ARGS, "--scenario-file", write_scenario(tmp_path, SCENARIO))
    assert code == 0 and Path(good["png"]["path"]).is_file()
    code, bad = run_capture(tmp_path, *BASE_ARGS, "--scenario-file", write_scenario(tmp_path, "{nope"))
    assert code == 1 and bad["png"]["path"] == good["png"]["path"] and bad["png"]["pixels"] is None
    assert not Path(bad["png"]["path"]).exists()


def test_a_widget_with_no_fixture_cannot_be_captured(built, tmp_path: Path, monkeypatch) -> None:
    from scripts.widgets import capture_one

    with pytest.raises(capture_one.CaptureFailed, match="ships no fixture"):
        capture_one.find_size([{"key": "core.x", "fixture": False, "sizes": {"home": [{"name": "m"}]}}], "core.x", "home", "m")


def test_a_simulated_edit_saves_and_reloads_inside_the_scenario_only(page_and_base) -> None:
    page, base = page_and_base
    page.set_viewport_size({"width": 1600, "height": 1100})
    outgoing: list[str] = []
    page.on("request", lambda request: outgoing.append(request.url) if "/api/" in request.url else None)
    harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": "carnivore"}, scenario=json.dumps(SCENARIO))
    box = page.locator("[data-harness-cell] textarea")
    assert "scenario marker text" in box.input_value()
    box.fill("an edit made in the lab")
    read_note = "async () => (await (await fetch('/api/v1/sessions/cloude_billing-api/note')).json())"
    for _ in range(150):
        if page.evaluate(read_note)["body"] == "an edit made in the lab":
            break
        page.wait_for_timeout(100)
    saved = page.evaluate(read_note)
    assert saved["revision"] == 4 and saved["body"] == "an edit made in the lab"
    stale = page.evaluate("""async () => { const r = await fetch('/api/v1/sessions/cloude_billing-api/note', {method: 'PUT',
        body: JSON.stringify({body: 'late', expected_revision: 1})}); return r.status; }""")
    assert stale == 409
    assert outgoing == [], f"a request left the page: {outgoing}"
    harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": "carnivore"})
    assert "retry policy" in page.locator("[data-harness-cell] textarea").input_value()


def test_the_harness_page_never_touches_the_apps_real_token(page_and_base) -> None:
    page, base = page_and_base
    page.goto(f"{base}/static/manifest.webmanifest")
    page.evaluate("() => { localStorage.setItem('claude_tunnel_token', 'REAL-TOKEN'); localStorage.setItem('claude_tunnel_refresh', 'REAL-REFRESH'); }")
    harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": "carnivore"})
    seen = page.evaluate("() => ({ token: localStorage.getItem('claude_tunnel_token'), refresh: localStorage.getItem('claude_tunnel_refresh'), n: localStorage.length })")
    assert seen == {"token": "widget-harness-placeholder", "refresh": None, "n": 1}
    page.evaluate("() => { localStorage.setItem('claude_tunnel_token', 'rotated'); localStorage.clear(); }")
    page.goto(f"{base}/static/manifest.webmanifest")
    real = page.evaluate("() => ({ token: localStorage.getItem('claude_tunnel_token'), refresh: localStorage.getItem('claude_tunnel_refresh') })")
    assert real == {"token": "REAL-TOKEN", "refresh": "REAL-REFRESH"}
    page.evaluate("() => localStorage.clear()")
