
from __future__ import annotations

import asyncio
import gzip
import io
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import themes_routes
from src.api.shell.static import NoCacheStaticFiles
from src.core import static_asset_keys
from src.core.boot import shell_bundle
from src.core.listing_push.publisher import Collection, CollectionResult, ListingPublisher
from src.core.pipeline.engine import Engine
from src.core.session_token_usage.cache import TranscriptTotals
from src.core.session_token_usage.claude_reader import _may_affect_totals, scan_lines
from src.plugins.host.runtime import Host
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.manifest import Manifest, Surfaces

CLIENT_DIR = Path(__file__).resolve().parents[3] / "client"


def test_claude_reader_prefilter_matches_exact_semantics_and_malformed_lines() -> None:
    lines = [
        json.dumps({"type": "progress", "data": {"blob": "x" * 2048}}).encode() + b"\n",
        json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}).encode() + b"\n",
        json.dumps({
            "type": "assistant",
            "effort": "high",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-6",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 20,
                },
            },
        }).encode() + b"\n",
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }).encode() + b"\n",
        json.dumps({
            "type": "system",
            "subtype": "local_command",
            "content": "Set effort level to xhigh (this session only): deep",
        }).encode() + b"\n",
        json.dumps({
            "type": "attachment",
            "attachment": {"type": "ultra_effort_enter"},
        }).encode() + b"\n",
        b"{not valid json}\n",
        b"[1, 2, 3]\n",
        b"truncated garbage\n",
    ]
    assert _may_affect_totals(lines[0].strip()) is False
    assert _may_affect_totals(lines[1].strip()) is False
    assert _may_affect_totals(lines[2].strip()) is True
    assert _may_affect_totals(lines[4].strip()) is True
    assert _may_affect_totals(lines[5].strip()) is True
    assert _may_affect_totals(lines[6].strip()) is True

    totals, offset = scan_lines(io.BytesIO(b"".join(lines)), TranscriptTotals())
    assert offset == sum(len(ln) for ln in lines)
    assert totals.input_tokens == 100
    assert totals.output_tokens == 50
    assert totals.cache_creation_input_tokens == 10
    assert totals.cache_read_input_tokens == 20
    assert totals.last_message_id == "msg_1"
    assert totals.last_model == "claude-opus-4-6"
    assert totals.last_effort == "xhigh"
    assert totals.ultra_effort is True
    assert totals.malformed_lines == 3


def test_shell_bundle_collapses_contiguous_runs_rewrites_urls_and_invalidates(tmp_path: Path) -> None:
    shell_bundle.reset_for_tests()
    static_asset_keys.reset_for_tests()
    css_sub = tmp_path / "css" / "sub"
    css_sub.mkdir(parents=True)
    js_dir = tmp_path / "js"
    js_dir.mkdir(parents=True)
    (tmp_path / "css" / "a.css").write_text("body{color:red}\n/*# sourceMappingURL=a.css.map */\n", encoding="utf-8")
    (css_sub / "b.css").write_text(".x{background:url('../img/p.png')}\n", encoding="utf-8")
    (js_dir / "one.js").write_text("window.__a = 1 // trailing comment no newline", encoding="utf-8")
    (js_dir / "two.js").write_text("(function(){ window.__b = 2; })()\n//# sourceMappingURL=two.js.map\n", encoding="utf-8")

    html = (
        '<link rel="stylesheet" href="/static/css/a.css" />\n'
        '<!-- comment allowed inside run -->\n'
        '<link rel="stylesheet" href="/static/css/sub/b.css" />\n'
        '<script src="/static/js/one.js"></script>\n'
        '<script src="/static/js/two.js"></script>\n'
        '<script type="module" src="/static/dist/app.js"></script>\n'
    )
    rendered = shell_bundle.render_bundled_shell(html, tmp_path)
    assert "/static/_bundle/css-0.css?v=" in rendered
    assert "/static/_bundle/js-0.js?v=" in rendered
    assert "/static/css/a.css" not in rendered
    assert "/static/js/one.js" not in rendered
    assert '<script type="module" src="/static/dist/app.js"></script>' in rendered

    app = FastAPI()
    app.mount("/static", NoCacheStaticFiles(directory=str(tmp_path)), name="static")
    client = TestClient(app)

    css_url = rendered.split('href="')[1].split('"')[0]
    js_url = rendered.split('src="')[1].split('"')[0]

    css_res = client.get(css_url, headers={"Accept-Encoding": "gzip"})
    assert css_res.status_code == 200
    assert css_res.headers["cache-control"] == static_asset_keys.IMMUTABLE
    assert css_res.headers["content-encoding"] == "gzip"
    assert "url('/static/css/img/p.png')" in css_res.text
    assert "sourceMappingURL" not in css_res.text

    not_mod = client.get(css_url, headers={"If-None-Match": css_res.headers["etag"]})
    assert not_mod.status_code == 304
    assert not_mod.headers["cache-control"] == static_asset_keys.IMMUTABLE

    stale_res = client.get("/static/_bundle/css-0.css?v=000000000000")
    assert stale_res.status_code == 200
    assert stale_res.headers["cache-control"] == static_asset_keys.REVALIDATE

    assert client.get("/static/_bundle/nope.js").status_code == 404
    assert shell_bundle.serve_bundle("_bundle/../js/one.js", {"type": "http", "headers": [], "query_string": b""}, tmp_path) is None

    js_res = client.get(js_url)
    assert js_res.status_code == 200
    assert "window.__a = 1 // trailing comment no newline\n;\n(function(){ window.__b = 2; })()" in js_res.text

    (js_dir / "two.js").write_text("(function(){ window.__b = 99; })()\n", encoding="utf-8")
    rerendered = shell_bundle.render_bundled_shell(html, tmp_path)
    js_url_v2 = rerendered.split('src="')[1].split('"')[0]
    assert js_url_v2 != js_url
    assert "window.__b = 99" in client.get(js_url_v2).text


def test_real_shell_bundles_cleanly_and_passes_node_syntax_check() -> None:
    shell_bundle.reset_for_tests()
    html = (CLIENT_DIR / "index.html").read_text(encoding="utf-8")
    bundled = shell_bundle.render_bundled_shell(html, CLIENT_DIR)
    assert bundled.count("/static/_bundle/css-") >= 1
    assert bundled.count("/static/_bundle/js-") >= 1
    assert bundled.count('<script src="/static/js/') == 0
    assert bundled.count('<link rel="stylesheet" href="/static/css/') == 0

    app = FastAPI()
    app.mount("/static", NoCacheStaticFiles(directory=str(CLIENT_DIR)), name="static")
    client = TestClient(app)
    js_url = [p.split('"')[0] for p in bundled.split('src="') if p.startswith("/static/_bundle/js-")][0]
    res = client.get(js_url, headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers["content-encoding"] == "gzip"
    assert len(res.content) > 100_000
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8") as tmp:
        tmp.write(res.text)
        tmp.flush()
        chk = subprocess.run(["node", "--check", tmp.name], capture_output=True, text=True, check=False)
        assert chk.returncode == 0, f"bundled JS failed node --check: {chk.stderr}"


def test_listing_publisher_runs_tier0_concurrently_before_tier1() -> None:
    async def go() -> None:
        in_tier0 = 0
        max_parallel = 0
        tier0_both_entered = asyncio.Event()
        seen_context_in_tier1: set[str] = set()

        async def make_t0(tag: str, ctx: dict) -> CollectionResult:
            nonlocal in_tier0, max_parallel
            in_tier0 += 1
            max_parallel = max(max_parallel, in_tier0)
            if in_tier0 == 2:
                tier0_both_entered.set()
            await asyncio.wait_for(tier0_both_entered.wait(), timeout=2.0)
            ctx.setdefault("seen", set()).add(tag)
            in_tier0 -= 1
            return CollectionResult(rows=[{"id": tag}])

        async def build_t1(ctx: dict) -> CollectionResult:
            seen_context_in_tier1.update(ctx.get("seen", set()))
            return CollectionResult(rows=[{"id": "after"}])

        pub = ListingPublisher(
            [
                Collection("a", lambda c: make_t0("a", c), lambda r: r["id"], tier=0),
                Collection("b", lambda c: make_t0("b", c), lambda r: r["id"], tier=0),
                Collection("c", build_t1, lambda r: r["id"], tier=1),
            ],
            publish=lambda _f: 1,
            client_count=lambda: 1,
        )
        frame = await pub.run_pass()
        assert frame is not None
        assert max_parallel == 2
        assert seen_context_in_tier1 == {"a", "b"}

    asyncio.run(go())


def test_plugin_host_start_parallelizes_independent_plugins_and_respects_requires(tmp_path: Path, monkeypatch) -> None:
    from src.plugins.host import runtime as host_runtime

    async def go() -> None:
        order: list[str] = []
        both_independent = asyncio.Event()
        entered = 0

        async def start_indep(name: str) -> None:
            nonlocal entered
            entered += 1
            if entered == 2:
                both_independent.set()
            await asyncio.wait_for(both_independent.wait(), timeout=2.0)
            order.append(name)

        async def start_dep(_ctx) -> None:
            order.append("dep")

        def make_def(cid: str, requires: tuple[str, ...], hook) -> CplugDefinition:
            manifest = Manifest(
                id=cid,
                name_key=f"cplug.{cid}.name",
                description_key=f"cplug.{cid}.desc",
                version="1.0.0",
                icon="bolt",
                author="test",
                min_app_version="0.1.0",
                tier="builtin",
                default_enabled=True,
                permissions=(),
                requires=requires,
                surfaces=Surfaces(),
            )
            return CplugDefinition(manifest=manifest, on_start=hook)

        defs = (
            make_def("alpha", (), lambda _ctx: start_indep("alpha")),
            make_def("bravo", (), lambda _ctx: start_indep("bravo")),
            make_def("charlie", ("alpha",), start_dep),
        )
        monkeypatch.setattr(host_runtime, "definitions", lambda: defs)
        host = Host(tmp_path, app=SimpleNamespace(state=SimpleNamespace()))
        monkeypatch.setattr(host, "enabled", lambda _cid: True)
        await host.start()
        assert set(order[:2]) == {"alpha", "bravo"}
        assert order[2] == "dep"

    asyncio.run(go())


def test_pipeline_engine_boot_scan_delay_defers_bulk_scan_not_live_work(tmp_path: Path) -> None:
    waits: list[float] = []

    def fake_wait(ev: threading.Event, timeout: float | None) -> bool:
        if timeout is not None:
            waits.append(timeout)
        ev.set()
        return True

    engine = Engine(
        tmp_path,
        plugins=(),
        wait=fake_wait,
        boot_scan_delay=15.0,
        notify=lambda: None,
    )
    engine.run_scan()
    assert waits == [15.0]
    assert engine.scan_ticks == 0


def test_warm_themes_cache_populates_root_scan_cache() -> None:
    with themes_routes._ROOT_SCAN_LOCK:
        themes_routes._ROOT_SCAN_CACHE.clear()
    count = themes_routes.warm_themes_cache()
    assert count > 0
    with themes_routes._ROOT_SCAN_LOCK:
        assert len(themes_routes._ROOT_SCAN_CACHE) >= 1


def test_per_request_stat_short_circuit_and_byte_prefilter(tmp_path: Path, monkeypatch) -> None:
    from src.core.session_token_usage import per_request

    per_request.clear()
    transcript = tmp_path / "conv.jsonl"
    transcript.write_text(
        json.dumps({"type": "progress", "data": "noise" * 200}) + "\n"
        + json.dumps({
            "type": "assistant",
            "requestId": "req_1",
            "timestamp": "2026-11-23T10:00:00Z",
            "message": {"id": "m1", "model": "claude-opus-4-6", "usage": {"input_tokens": 10, "output_tokens": 5}},
        }) + "\n",
        encoding="utf-8",
    )
    rows, total, _ = per_request.read_conversation_requests(transcript)
    assert total == 1 and rows[0].request_id == "req_1"
    assert per_request.MAX_FILES >= 8192

    real_open = open

    def forbid_open(*args, **kwargs):
        raise AssertionError("unchanged transcript file must not be reopened")

    monkeypatch.setattr("builtins.open", forbid_open)
    rows2, total2, _ = per_request.read_conversation_requests(transcript)
    assert total2 == 1 and rows2[0].request_id == "req_1"
    rows3, total3, _ = per_request.read_conversation_requests(transcript, since="2026-11-24T00:00:00Z")
    assert total3 == 0 and rows3 == []
    monkeypatch.setattr("builtins.open", real_open)


def test_per_request_cold_boot_skips_ancient_files_by_mtime_when_since_set(tmp_path: Path, monkeypatch) -> None:
    import os
    from src.core.session_token_usage import per_request

    per_request.clear()
    transcript = tmp_path / "old.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant",
            "requestId": "req_old",
            "timestamp": "2026-10-01T00:00:00Z",
            "message": {"id": "m_old", "model": "claude-opus-4-6", "usage": {"input_tokens": 5, "output_tokens": 2}},
        }) + "\n",
        encoding="utf-8",
    )
    old_ts = 1790812800.0
    os.utime(transcript, (old_ts, old_ts))

    real_open = open

    def forbid_open(*args, **kwargs):
        raise AssertionError("cold file older than since - 5m must not be opened")

    monkeypatch.setattr("builtins.open", forbid_open)
    rows, total, _ = per_request.read_conversation_requests(transcript, since="2026-11-23T00:00:00Z")
    assert total == 0 and rows == []

    monkeypatch.setattr("builtins.open", real_open)
    rows_all, total_all, _ = per_request.read_conversation_requests(transcript)
    assert total_all == 1 and rows_all[0].request_id == "req_old"


def test_agy_state_for_conversation_caches_by_stat_and_invalidates(tmp_path: Path, monkeypatch) -> None:
    from src.core.agy import state as agy_state

    folder = tmp_path / agy_state.STATE_FOLDER
    folder.mkdir(parents=True)
    f = folder / "12345.json"
    f.write_text(json.dumps({"conversation_id": "conv-1", "written_at": 100, "agent_state": "idle"}), encoding="utf-8")

    first = agy_state.state_for_conversation(tmp_path, "conv-1")
    assert first is not None and first["agent_state"] == "idle"

    real_open = open
    monkeypatch.setattr("builtins.open", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must hit stat cache")))
    second = agy_state.state_for_conversation(tmp_path, "conv-1")
    assert second is not None and second["agent_state"] == "idle"

    monkeypatch.setattr("builtins.open", real_open)
    f.write_text(json.dumps({"conversation_id": "conv-1", "written_at": 200, "agent_state": "working"}), encoding="utf-8")
    third = agy_state.state_for_conversation(tmp_path, "conv-1")
    assert third is not None and third["agent_state"] == "working"


def test_shell_bundle_refuses_a_css_member_whose_braces_do_not_pair_up(tmp_path: Path) -> None:
    shell_bundle.reset_for_tests()
    static_asset_keys.reset_for_tests()
    css = tmp_path / "css"
    css.mkdir()
    (css / "a.css").write_text("@layer components {\n.a{color:red}\n", encoding="utf-8")
    (css / "b.css").write_text(".b{content:'}'}\n/* { */\n", encoding="utf-8")
    html = '<link rel="stylesheet" href="/static/css/a.css" />\n<link rel="stylesheet" href="/static/css/b.css" />\n'
    assert shell_bundle.render_bundled_shell(html, tmp_path) == html
    (css / "a.css").write_text("@layer components {\n.a{color:red}\n}\n", encoding="utf-8")
    assert "/static/_bundle/css-0.css?v=" in shell_bundle.render_bundled_shell(html, tmp_path)


def test_real_shell_stylesheets_all_pair_their_braces() -> None:
    import re

    client = Path(__file__).resolve().parents[3] / "client"
    hrefs = re.findall(r'href="/static/([^"?]+\.css)"', (client / "index.html").read_text(encoding="utf-8"))
    assert hrefs
    unbalanced = [h for h in hrefs if not shell_bundle._css_braces_balanced((client / h).read_text(encoding="utf-8"))]
    assert unbalanced == []
