
from __future__ import annotations

import contextlib
import gc
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.db_migration import ensure_db_migrated
from src.plugins.host import ui_doc
from src.plugins.host.ui_doc_markdown import check_markdown_safe_violation
from src.plugins.sdk._manifest_v2_sections import ManifestV2Error
from src.plugins.sdk.manifest import NetworkDecl
from src.plugins.sdk.manifest_v2 import parse_manifest_v2
from tests.python.api_keys.conftest import bearer, owner_jwt  # noqa: F401


def test_ui_doc_schema_v2_all_21_primitives_and_v1_compat() -> None:
    assert ui_doc.SCHEMA == 2
    assert ui_doc.SUPPORTED_SCHEMAS == frozenset({1, 2})
    assert len(ui_doc._FIELDS) == 21

    v1_doc = {"schema": 1, "root": {"type": "section", "title": "v1", "children": [{"type": "text", "value": "hi"}]}}
    rebuilt_v1 = ui_doc.validate(v1_doc, routes=(), tools=())
    assert rebuilt_v1["schema"] == 1

    with pytest.raises(ui_doc.UiDocError) as exc_v1:
        ui_doc.validate({"schema": 1, "root": {"type": "sparkline", "values": [1, 2, 3]}}, routes=(), tools=())
    assert exc_v1.value.code == "unknown_node"

    with pytest.raises(ui_doc.UiDocError) as exc_v3:
        ui_doc.validate({"schema": 3, "root": {"type": "text", "value": "x"}}, routes=(), tools=())
    assert exc_v3.value.code == "bad_schema"

    v2_doc = {
        "schema": 2,
        "root": {
            "type": "section",
            "title": "All 21",
            "children": [
                {
                    "type": "row",
                    "gap": 2,
                    "wrap": True,
                    "children": [
                        {
                            "type": "column",
                            "children": [
                                {"type": "text", "value": "hello", "tone": "normal"},
                                {"type": "badge", "text": "beta", "tone": "accent"},
                                {"type": "stat", "label": "Calls", "value": 42, "unit": "rpm", "delta": "+4"},
                                {"type": "meter", "label": "Mem", "value": 32, "max": 128, "thresholds": [64, 96]},
                                {"type": "progress", "label": "Sync", "value": 50, "max": 100, "tone": "accent"},
                                {"type": "sparkline", "values": [1, 2.5, 4], "label": "Latency", "tone": "normal"},
                            ],
                        },
                        {
                            "type": "list",
                            "empty": "None",
                            "items": [
                                {"type": "table", "columns": ["K", "V"], "rows": [["a", 1]]},
                                {"type": "button", "label": "Ping", "action": {"call": "route", "route": "save"}},
                                {"type": "empty_state", "title": "Clean", "description": "No errors", "action": {"call": "tool", "name": "scan"}},
                            ],
                        },
                    ],
                },
                {
                    "type": "form",
                    "action": {"call": "route", "route": "save"},
                    "submit_label": "Apply",
                    "children": [
                        {"type": "input", "name": "host", "label": "Host", "input_type": "text", "required": True, "placeholder": "localhost"},
                        {"type": "textarea", "name": "notes", "label": "Notes", "rows": 4},
                        {"type": "select", "name": "mode", "label": "Mode", "options": ["fast", {"value": "safe", "label": "Safe"}], "value": "fast"},
                        {"type": "toggle", "name": "auto", "label": "Auto", "checked": True, "tone": "accent"},
                    ],
                },
                {
                    "type": "tabs",
                    "active": "code_tab",
                    "items": [
                        {"id": "code_tab", "label": "Code", "content": {"type": "code", "value": "ok", "language": "json"}},
                        {"id": "md_tab", "label": "Docs", "children": [{"type": "markdown_safe", "value": "## Overview"}]},
                    ],
                },
            ],
        },
    }
    rebuilt_v2 = ui_doc.validate(v2_doc, routes=("save",), tools=("scan",))
    assert rebuilt_v2["schema"] == 2

    with pytest.raises(ui_doc.UiDocError) as exc_link:
        ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": "javascript:alert(1)"}}, routes=(), tools=())
    assert exc_link.value.code == "link_not_allowed"

    with pytest.raises(ui_doc.UiDocError) as exc_nan:
        ui_doc.validate({"schema": 2, "root": {"type": "sparkline", "values": [float("nan")]}}, routes=(), tools=())
    assert exc_nan.value.code == "not_json"


def test_manifest_v2_accepts_schema_1_and_2_widget_documents() -> None:
    base = """schema = 2
id = "wplug"
name = "Widget Plug"
kind = "plugin"
description = "Widget v2"
author = "Tester"
license = "MIT"
version = "1.0.0"
"""
    for doc_schema in (1, 2):
        toml = base + f"""
[ui.widget.document]
schema = {doc_schema}
[ui.widget.document.root]
type = "text"
value = "hello"
"""
        parsed = parse_manifest_v2(tomllib.loads(toml))
        assert parsed.ui_meta.get("widget") is not None
        assert parsed.ui_meta["widget"]["document"]["schema"] == doc_schema

    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(
            tomllib.loads(base + """
[ui.widget.document]
schema = 3
[ui.widget.document.root]
type = "text"
value = "hello"
""")
        )


def test_owner_act_allows_omitted_session_ref(tmp_path: Path, owner_jwt, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    calls: list[tuple[str, Any]] = []

    class _FakeProc:
        ended = None

        async def request(self, method: str, params: Any, timeout: float = 5.0) -> Any:
            calls.append((method, params))
            return {"status": 200, "body": {"saved": True, "session_ref": params["session_ref"], "owner_token": params["owner_token"]}}

    class _FakeSup:
        def state(self, pid: str) -> str:
            return "running"

        def is_paused(self, pid: str) -> bool:
            return False

        async def ensure(self, pid: str) -> Any:
            return _FakeProc()

    class _FakeRuntime:
        def __init__(self) -> None:
            from src.plugins.runtime.owner_tokens import OwnerTokens

            self.tokens = OwnerTokens()
            self.supervisor = _FakeSup()

        def safe_mode(self) -> dict[str, bool]:
            return {"env": False, "switch": False, "route": False}

    from src.plugins.host.plugin_manifest import SidecarManifest
    from src.plugins.host.sidecar_registry import SidecarDefinition

    manifest = SidecarManifest(
        id="panelplug",
        name="Panel Plug",
        description="Panel",
        version="1.0.0",
        entry="main.py",
        tools=(),
        permissions=(),
        network=NetworkDecl(),
        author="Acme",
        tier="catalog",
        code_digest="deadbeef",
        routes=("save",),
    )
    fake_defn = SidecarDefinition(manifest, "acme/panelplug", "uuid-panelplug", tmp_path, tmp_path / "data", "PUBKEY")

    from src.plugins.host import runtime as host_runtime

    monkeypatch.setattr("src.plugins.host.sidecar_routes.runtime.find", lambda cid: fake_defn if cid == "panelplug" else None)
    monkeypatch.setattr("src.plugins.host.sidecar_routes.runtime.hidden", lambda _d: False)
    fake_host = host_runtime.Host(state, app)
    monkeypatch.setattr(fake_host, "enabled", lambda _pid: True)
    monkeypatch.setattr(fake_host, "sidecar_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(fake_host, "install_key", lambda pid: f"key-{pid}")
    app.state.cplugs_host = fake_host

    try:
        with TestClient(app) as tc:
            r = tc.post(
                "/api/v1/cplug-owner/act",
                json={"cplug_id": "panelplug", "route": "save", "body": {"host": "127.0.0.1"}},
                headers=bearer(owner_jwt),
            )
            assert r.status_code == 200, r.text
            assert r.json() == {"saved": True, "session_ref": None, "owner_token": None}
            assert len(calls) == 1
    finally:
        if hasattr(app.state, "cplugs_host"):
            delattr(app.state, "cplugs_host")


def test_markdown_safe_rejects_raw_html_and_entity_schemes_and_allows_code_blocks() -> None:
    for payload, expected_code in (
        ("<script>alert(1)</script>", "html_not_allowed"),
        ("<iframe src='x'></iframe>", "html_not_allowed"),
        ("<img src=x onerror=alert(1)>", "html_not_allowed"),
        ("<!-- hidden html -->", "html_not_allowed"),
        ("[click](javascript&#58;alert(1))", "link_not_allowed"),
        ("[click](&#x6a;avascript:alert(1))", "link_not_allowed"),
        ("[click](java&#x09;script:alert(1))", "link_not_allowed"),
        ("[click](javascript&colon;alert(1))", "link_not_allowed"),
        ("[click](java&Tab;script&colon;alert(1))", "link_not_allowed"),
        ("```\ncode\n````\n<script>alert(1)</script>\n```", "html_not_allowed"),
        ("~~~\ncode\n~~~~\n<script>alert(1)</script>\n~~~", "html_not_allowed"),
        ("```lang`bad\n<script>alert(1)</script>\n```", "html_not_allowed"),
        ("\\`<script>alert(1)</script>`", "html_not_allowed"),
        ("\\\\\\`<script>alert(1)</script>`", "html_not_allowed"),
        ("\\``<script>alert(1)</script>``", "html_not_allowed"),
        ("`a\\`<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("``\n``<img src=x onerror=alert(1)>``", "html_not_allowed"),
        ("`foo\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("> `\n> `<script>alert(1)</script>`", "html_not_allowed"),
        ("`hello\n<script>inside</script>`", "html_not_allowed"),
        ("    `hello\n<script>alert(1)</script>`", "html_not_allowed"),
        ("`hello\n---\n<script>alert(1)</script>`", "html_not_allowed"),
        ("`hello\n> <script>alert(1)</script>`", "html_not_allowed"),
        ("[click](\njavascrip&#x0a;t&#x3a;alert(1))", "link_not_allowed"),
        ("[click][x]\n\n[x]:\njavascrip&#x0a;t&#x3a;alert(1)", "link_not_allowed"),
        ("[click](\n  <javascript:alert(1)>)", "link_not_allowed"),
        ("`\n2. `<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n2) `<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n0. `<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n+\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n*\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n* \n`<script>alert(1)</script>`", "html_not_allowed"),
        ("`\n1.\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("    \nfoo `\n1. \n`<script>alert(1)</script>`", "html_not_allowed"),
        ("- `\n===\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("> `\n===\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("- `\n--\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("> `\n--\n`<script>alert(1)</script>`", "html_not_allowed"),
        ("> `\n> 2. `<script>alert(1)</script>`", "html_not_allowed"),
        ("[click][a\\]b]\n\n[a\\]b]: javascrip&#x0a;t&#x3a;alert(1)", "link_not_allowed"),
        ("> [click][a\\]b]\n>\n> [a\\]b]: javascrip&#x0a;t&#x3a;alert(1)", "link_not_allowed"),
        ("[click](javascrip&#x0a;t\\:alert\\(1\\))", "link_not_allowed"),
        ("[click](javascrip&#x09;t\\:alert\\(1\\))", "link_not_allowed"),
        ("[click][x]\n\n[x]: javascrip&#x0a;t\\:alert(1)", "link_not_allowed"),
        ("![alt](javascrip&#x0a;t\\:alert\\(1\\))", "link_not_allowed"),
        ("[click](dat&#x0a;a\\:text/html,hi)", "link_not_allowed"),
        ("[click](vbscrip&#x0a;t\\:msgbox\\(1\\))", "link_not_allowed"),
        ("[click](https\\://evil.com)", "link_not_allowed"),
        ("![alt](https\\://evil.com/x.png)", "link_not_allowed"),
        ("[click][x]\n\n[x]: https\\://evil.com", "link_not_allowed"),
        ("> [a\n> b]: https\\://evil.com\n>\n> [click][a\n> b]", "link_not_allowed"),
        ("> [click](\n> javascrip&#x0a;t&#x3a;alert(1))", "link_not_allowed"),
        ("> [click]( \n> javascrip&#x0a;t&#x3a;alert(1))", "link_not_allowed"),
        ("- > [click](\n  > javascrip&#x0a;t&#x3a;alert(1))", "link_not_allowed"),
        ("> - [click](\n>   javascrip&#x0a;t&#x3a;alert(1))", "link_not_allowed"),
        ("[click](https\\://a\\)b \"title\")", "link_not_allowed"),
        ("[click][x]\n\n[x]: < javascrip&#x0a;t\\:alert(1)>", "link_not_allowed"),
        ("<https://evil.com>", "link_not_allowed"),
        ("<javascript:alert(1)>", "link_not_allowed"),
        ("<user@example.com>", "link_not_allowed"),
        ("[click](&ensp;https://evil.com)", "link_not_allowed"),
        ("> - ![alt](&hairsp;javascrip&#x0a;t\\:alert\\(1\\))", "link_not_allowed"),
        ("0. ![alt](&thinsp;vbscrip&#x09;t&colon;//evil.com)", "link_not_allowed"),
        ("[click](&NonBreakingSpace;https://evil.com)", "link_not_allowed"),
        ("hello&ensp;http://x", "link_not_allowed"),
        ("<?php echo 1; ?>", "html_not_allowed"),
        ("<?xml version=\"1.0\"?>", "html_not_allowed"),
        ("- `\n- > *** <?php echo 1; ?>", "html_not_allowed"),
        ("foo\n- 2. <?php echo 1; ?>", "html_not_allowed"),
        ("[click](&nbsp;a:1)", "link_not_allowed"),
        ("- > ![alt](&nbsp;a\\:alert\\(1\\))", "link_not_allowed"),
        ("[click](\u2002a:1)", "link_not_allowed"),
        ("> [click](\u00a0//evil.com)", "link_not_allowed"),
        ("[click](//evil.com)", "link_not_allowed"),
        ("[click](javascrip&#x0b;t:alert(1))", "link_not_allowed"),
        ("[a](b \"`\") <script>alert(1)</script> `x`", "html_not_allowed"),
        ("<span title=\"`\"><script>alert(1)</script>`x`", "html_not_allowed"),
        ("<?php echo 1", "html_not_allowed"),
        ("<!DOCTYPE html", "html_not_allowed"),
        ("<![CDATA[ alert(1)", "html_not_allowed"),
        ("<div", "html_not_allowed"),
        ("[click](&emsp13;https://evil.com)", "link_not_allowed"),
        ("[click](&emsp14;a:1)", "link_not_allowed"),
        ("100. foo\n    ```\n<script>alert(1)</script>", "html_not_allowed"),
        ("100. foo\n    ~~~\n<script>alert(1)</script>", "html_not_allowed"),
        ("1000. foo\n     ```\n<script>alert(1)</script>", "html_not_allowed"),
        ("100. foo\n    ```\n<img src=x onerror=alert(1)>", "html_not_allowed"),
        ("100. foo\n    ```\n<?php echo 1", "html_not_allowed"),
        ("100. foo\n    ```\n[x](//evil.com)", "link_not_allowed"),
        ("100. foo\n    ```\n[x](a:1)", "link_not_allowed"),
        ("> 100. foo\n>     ```\n> <script>alert(1)</script>", "html_not_allowed"),
        ("100. `foo\n    ```\n<script>alert(1)</script>`", "html_not_allowed"),
        ("100. `foo\n    <div>\n<script>alert(1)</script>`", "html_not_allowed"),
        ("> 100. `foo\n>     ```\n> <script>alert(1)</script>`", "html_not_allowed"),
        (">     ```\n    > <script>alert(1)</script>", "html_not_allowed"),
        ("> 100. foo\n    > <script>alert(1)</script>", "html_not_allowed"),
        ("[a]: x\\\n<script>alert(1)</script>", "html_not_allowed"),
        ("[a]: x\\\n# <script>alert(1)</script>", "html_not_allowed"),
        ("[a]: x\\\n> <script>alert(1)</script>", "html_not_allowed"),
        ("[a]: x\\\n```\n```\n<script>alert(1)</script>", "html_not_allowed"),
        ("> [a]: x\\\n> <script>alert(1)</script>", "html_not_allowed"),
        ("100. [a]: x\\\n     <script>alert(1)</script>", "html_not_allowed"),
        ("[a]: x\\\n<div\nonclick=1>", "html_not_allowed"),
        ("[a]: x\\\n\"`\"\n`<script>alert(1)</script>`\n\n[a]", "html_not_allowed"),
        ("[a](//evil.com\\\ny)", "link_not_allowed"),
        ("[a](<//evil.com\\\ny>)", "link_not_allowed"),
        ("a <a x=1\u00a0y =2>", "html_not_allowed"),
        ("<a x=1\u00a0y =2>", "html_not_allowed"),
        ("a <a x=\u00a0\u00a0y =2>", "html_not_allowed"),
        ("a <a x=1\u00a0y\n=2>", "html_not_allowed"),
        ("a <a x=1\u00a0y ='2'>", "html_not_allowed"),
        ('a <a x=1\u00a0y ="2">', "html_not_allowed"),
        ("a <a x=1\u00a0y=2\u00a0z =3>", "html_not_allowed"),
        ("a <a x=\u00a01\u00a0y =2>", "html_not_allowed"),
        ("a <a x=1\u2002y =2>", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`a`", "html_not_allowed"),
        ("\\\\<)[`--->\n</a></divhttps:`\\\\`\u3000``", "html_not_allowed"),
        ("![`<img src=x onerror=alert(1)>`a`", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`a`](ok)", "html_not_allowed"),
        ("[[`<script>`] `", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<script>alert(1)</script>`][ `\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][`\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][a `]\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][[a] `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][`a` `\n\n[a]: ok", "html_not_allowed"),
        ("[[`<img src=x>`]][`\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][a `]\n\n[a `]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](x/]) unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](<x/]>) unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](<]> ) `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](<]>) `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][![a](x/]) unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][![a](<]>) `\n\n[a]: ok", "html_not_allowed"),
        ("[`<script>alert(1)</script>`][[a](x/]) `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](x \"t]\") unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](b \"]\") `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](x 't]') unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](x (])) unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](x (t])) unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][![a](x \"t]\") unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x onerror=alert(1)>`](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](a c[a `]\n\n[a]: ok", "html_not_allowed"),
        ("![`<script>alert(1)</script>`](<[`\n\n[a]: ok", "html_not_allowed"),
        ("![`<script>alert(1)</script>`](<[unclosed `\n\n[a]: ok", "html_not_allowed"),
        ("![ [b] `<img src=x>` ](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](<[ `\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](<[a `\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](x \"[ `\n\n[a]: ok", "html_not_allowed"),
        ("![`<img src=x>`](([ `\n\n[a]: ok", "html_not_allowed"),
        ("![ ![a](b) `<img src=x>` ](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("![ ![a] `<img src=x>` ](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("![ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("[ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok", "html_not_allowed"),
        ("[`<img src=x>`][<javascript:`>]\n\n[<javascript:`>]: ok", "link_not_allowed"),
        ("[`<img src=x onerror=alert(1)>`][[a](data:image/png;base64,x/]) `\n\n[a]: ok", "link_not_allowed"),
        ("[`<img src=x>` [top][ ![ ![a][ [b](c) ] ](([r](x/]) (`\n\n[top]: ok\n[r]: ok", "html_not_allowed"),
        ("[`<img src=x>` [top][ [a](javascript:1 ([b](y/]) (`\n\n[top]: ok\n[b]: ok", "html_not_allowed"),
        ("[`<img src=x>`](javascript:x [b] `<script>1</script>\n\n[b]: ok", "link_not_allowed"),
    ):
        with pytest.raises(ui_doc.UiDocError) as exc:
            ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
        assert exc.value.code == expected_code, payload

    for ctrl_payload in ("a <a x=1\u00a0y\t=2>", "a <a x=1\u00a0y\x0c=2>", "a <a x=1\u00a0y\x0b=2>"):
        assert check_markdown_safe_violation(ctrl_payload) == "html_not_allowed", repr(ctrl_payload)
    assert check_markdown_safe_violation("100. [a]: x\\\n    <script>alert(1)</script>") is None
    assert ui_doc.validate(
        {"schema": 2, "root": {"type": "markdown_safe", "value": "100. [a]: x\\\n    <script>alert(1)</script>"}},
        routes=(),
        tools=(),
    )["schema"] == 2
    assert ui_doc.validate(
        {"schema": 2, "root": {"type": "markdown_safe", "value": "[a]:\\"}},
        routes=(),
        tools=(),
    )["schema"] == 2

    for tab_payload, expected_tab_code in (
        ("1000. foo\n\t```\n<script>alert(1)</script>", "html_not_allowed"),
        ("100. foo\n    <script>alert(1)</script>", None),
        ('> >   > \t> <a title=">">\n', "html_not_allowed"),
        ('> > 1.   \t<a title=">">\n# h\nlazy', "html_not_allowed"),
        ("> >   > \t<a x=1\u00a0y =2>", "html_not_allowed"),
        ('> - > > \t<a title=">">', "html_not_allowed"),
        ("> >   > \t<script>alert(1)</script>", "html_not_allowed"),
        ("> >   > \t<img src=x onerror=alert(1)>", "html_not_allowed"),
        ("> > 1.   \t<img src=x onerror=alert(1)>", "html_not_allowed"),
        ("> - > > \t<img src=x onerror=alert(1)>", "html_not_allowed"),
        ("> >   > \t[click](//evil.com)", "link_not_allowed"),
        ("> > 1.   \t[click](//evil.com)", "link_not_allowed"),
        ("> - > > \t[click](//evil.com)", "link_not_allowed"),
        ("> > \t<script>alert(1)</script>", None),
        ("> >   \t<script>alert(1)</script>", None),
        ("-\n\n    `foo\n<script>alert(1)</script>`", "html_not_allowed"),
        ("> -\n>\n>     `foo\n> <script>alert(1)</script>`", "html_not_allowed"),
        ("- - -\n    `a\n<script>alert(1)</script>`", "html_not_allowed"),
    ):
        assert check_markdown_safe_violation(tab_payload) == expected_tab_code, repr(tab_payload)
    assert ui_doc.validate(
        {"schema": 2, "root": {"type": "markdown_safe", "value": "100. foo\n    <script>alert(1)</script>"}},
        routes=(),
        tools=(),
    )["schema"] == 2

    for safe_value in (
        "Use `<div>` inline or [docs](readme.md).\n\n```html\n<script>ok</script>\n```",
        "\\\\`<script>ok</script>`",
        "`` `a` <script>ok</script> ``",
        "[click](javascript&Colon;alert(1))",
        "[click](javascript&COLON;alert(1))",
        "`hello\nworld`",
        "`hello\n<span>inside</span>`",
        "`hello\nfoo <script>inside</script>`",
        "> `hello\n> world`",
        "[click](\nreadme.md)",
        "[click][x]\n\n[x]:\nreadme.md",
        "[click](java&#0;script:alert(1))",
        "[click](java&#x110000;script:alert(1))",
        "[click](javascrip&#x0a;t&#x5c;:alert(1))",
        "[click](https\\\\://evil.com)",
        "[click](https&#x5c;://evil.com)",
        "> [docs](\n> readme.md)",
        "hello &#x0b; world",
        "[click](&#x5c;:)",
        "[click](\\\\:)",
        "[time](12:30)",
        "a <? b",
        "\\<div class=\"x\">",
        "<a + b>",
        "    <script>alert(1)</script>",
        "x&Idot;http://evil.com",
        "[a `<script>`](ok)",
        "[ [a `<script>`](ok) `",
        "[`<script>`] `",
        "[`<script>`][a] `\n\n[a]: ok",
        "[ [a] `<img src=x>` ][`\n\n[a]: ok",
        "[`<script>`](ok) `",
        "![ [a](b) `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ [a] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![ [a](b) ] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![a](b c `<img src=x>` ](d e[`\n\n[a]: ok",
        "[`<img src=x>`][[ [a](b) ](x/]) `\n\n[a]: ok",
        "[`<img src=x>`][ [a][b](c/]) `\n\n[a]: ok\n[b]: ok",
        "[`<img src=x>`](   \n\n[a]: ok",
    ):
        safe_doc = {"schema": 2, "root": {"type": "markdown_safe", "value": safe_value}}
        assert ui_doc.validate(safe_doc, routes=(), tools=())["root"]["value"] == safe_value


def test_html5_entities_json_matches_python_stdlib_exactly() -> None:
    import html.entities
    import json

    repo_root = Path(__file__).resolve().parents[3]
    ts_entities = json.loads((repo_root / "web/src/lib/cplug-ui/html5-entities.json").read_text(encoding="utf-8"))
    py_entities = {k[:-1]: v for k, v in html.entities.html5.items() if k.endswith(";")}
    assert len(py_entities) == 2125
    assert ts_entities == py_entities


def test_form_enforces_unique_control_names_per_form_scope() -> None:
    dup_direct = {
        "schema": 2,
        "root": {
            "type": "form",
            "action": {"call": "route", "route": "save"},
            "children": [
                {"type": "input", "name": "dup_field", "label": "A"},
                {"type": "select", "name": "dup_field", "label": "B", "options": ["one"]},
            ],
        },
    }
    with pytest.raises(ui_doc.UiDocError) as exc_dup:
        ui_doc.validate(dup_direct, routes=("save",), tools=())
    assert exc_dup.value.code == "duplicate_field_name"

    dup_nested = {
        "schema": 2,
        "root": {
            "type": "form",
            "action": {"call": "route", "route": "save"},
            "children": [
                {"type": "row", "children": [{"type": "textarea", "name": "dup_field", "label": "A"}]},
                {"type": "toggle", "name": "dup_field", "label": "B"},
            ],
        },
    }
    with pytest.raises(ui_doc.UiDocError) as exc_nested:
        ui_doc.validate(dup_nested, routes=("save",), tools=())
    assert exc_nested.value.code == "duplicate_field_name"

    two_forms = {
        "schema": 2,
        "root": {
            "type": "column",
            "children": [
                {
                    "type": "form",
                    "action": {"call": "route", "route": "save"},
                    "children": [{"type": "input", "name": "query", "label": "Q1"}],
                },
                {
                    "type": "form",
                    "action": {"call": "route", "route": "save"},
                    "children": [{"type": "input", "name": "query", "label": "Q2"}],
                },
            ],
        },
    }
    assert ui_doc.validate(two_forms, routes=("save",), tools=())["schema"] == 2


@contextlib.contextmanager
def _gc_paused() -> Iterator[None]:
    was_enabled = gc.isenabled()
    if was_enabled:
        gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


def test_markdown_safe_nested_brackets_linear_time() -> None:
    cases = (
        ("[" * 64 + "]" * 64, None),
        ("[" * 500 + "]" * 500, None),
        ("[" * 300 + "a" + "](" * 100 + "b)", None),
        ("![" * 400 + "a" + "](" * 200, None),
        ("[" * 1000, None),
        ("[[" * 400 + "a](javascript:alert(1))" + "]]" * 200, "link_not_allowed"),
    )
    for payload, expected_err in cases:
        with _gc_paused():
            t0 = time.process_time()
            if expected_err is None:
                rebuilt = ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
                assert rebuilt["root"]["value"] == payload
            else:
                with pytest.raises(ui_doc.UiDocError) as exc:
                    ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
                assert exc.value.code == expected_err
            elapsed_ms = (time.process_time() - t0) * 1000.0
        assert elapsed_ms < 50.0, f"nested bracket case took {elapsed_ms:.2f}ms CPU (len={len(payload)})"


def test_markdown_safe_html_redos_eof_linear_time_and_nbsp_parity() -> None:
    timing_validate_cases = (
        ("a <a " + "x=\u00a0\u00a0 " * 50, None),
        ("<a " + "x=\u00a0\u00a0 " * 50, None),
        ("a <a x=" + "\u00a0" * 1900, None),
        ("<a x=" + "\u00a0" * 1900, None),
        ("a <a x=" + "\u00a0" * 1900 + " y=", None),
        ("<a x=" + "\u00a0" * 1900 + " y=", None),
        ("a " + "<!--" * 450, None),
        ("a " + "<!-- a ---> " * 150, None),
        ("a " + "<?" * 900, None),
        ("a " + "<![CDATA[" * 200, None),
        ("a " + "<!A" * 500, None),
        ("a " + "<div " * 399, None),
        ("a " + "<a " * 500 + ">", "html_not_allowed"),
        ("a " + "<a x=1 " * 250 + ">", "html_not_allowed"),
        ("a <a " + "x=1\u00a0y " * 200, None),
        ("[`" + "a`" * 500, None),
        ("[`a`][" * 200 + "`\n\n[a]: ok", None),
        ("[a]" * 200 + "[`\n\n[a]: ok", None),
        ("[a][" + "[b](x/]) " * 200 + "`\n\n[a]: ok", None),
        ("[a][" + "[b](x [" * 240 + "]" * 240 + "\n\n[a]: ok", None),
        ("[a][" + "[b](x [" * 260 + "`\n\n[a]: ok", None),
        ("![a][" + "![b](x/]) " * 190 + "`\n\n[a]: ok", None),
    )
    for payload, expected_err in timing_validate_cases:
        with _gc_paused():
            t0 = time.process_time()
            if expected_err is None:
                rebuilt = ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
                assert rebuilt["root"]["value"] == payload
            else:
                with pytest.raises(ui_doc.UiDocError) as exc:
                    ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
                assert exc.value.code == expected_err, payload
            elapsed_ms = (time.process_time() - t0) * 1000.0
        assert elapsed_ms < 50.0, f"HTML ReDoS/EOF case took {elapsed_ms:.2f}ms CPU (len={len(payload)})"

    for direct_bomb, expected_code in (
        ("a " + "<div " * 400, None),
        ("[a][" + "[b](x/]) " * 300 + "`\n\n[a]: ok", None),
        ("[a][" + "[b](x [" * 500 + "]" * 500 + "\n\n[a]: ok", None),
        ("[a][" + "[b](x [" * 500 + "`\n\n[a]: ok", None),
        ("![a][" + "![b](x/]) " * 300 + "`\n\n[a]: ok", None),
        ("[top][" + "[a][" * 4000 + "b" + "]" * 4000 + "]\n\n[top]: ok\n[b]: ok", None),
        ("[top][" + "\\[a\\][" * 4000 + "b" + "]" * 4000 + "]\n\n[top]: ok\n[b]: ok", None),
        ("[top][" + "[" * 4000 + "[b]" + "]" * 4000 + "]\n\n[top]: ok\n[b]: ok", None),
        ("[top][" + "[" * 4000 + "[b]" + "]" * 4000 + "] <script>1</script>\n\n[top]: ok\n[b]: ok", "html_not_allowed"),
        ("[top][" + "\\[a\\][" * 4000 + "b" + "]" * 4000 + "] <script>1</script>\n\n[top]: ok\n[b]: ok", "html_not_allowed"),
        ("- " * 4000 + "x\n" + "\n" * 4000, None),
        ("- " * 4000 + "x\n" + "\n" * 4000 + "<script>1</script>", "html_not_allowed"),
        ("- " * 4000 + "```\n" + "\n" * 4000 + "```", None),
        ("- " * 4000 + "x\n" + "y\n" * 4000, None),
        ("- " * 4000 + "x\n" + "y\n" * 4000 + "<script>1</script>", "html_not_allowed"),
        ("> " * 4000 + "x\n" + "y\n" * 4000, None),
        ("> " * 4000 + "x\n" + "y\n" * 4000 + "<script>1</script>", "html_not_allowed"),
        ("- " * 4000 + "[a\n" + "y\n" * 4000, None),
        ("> " + "- " * 4000 + "x\n" + ">\n" * 4000, None),
        ("> " + "- " * 4000 + "x\n" + ">\n" * 4000 + "> <script>1</script>", "html_not_allowed"),
        ("- " * 4000 + "x\n" + "  " * 4000 + "x", None),
        ("- " * 4000 + "x\n" + "  " * 4000 + "x<script>1</script>", "html_not_allowed"),
        ("> \t" * 2000 + "- \t" * 2000 + "x\n" + "y\n" * 4000, None),
        ("> \t" * 2000 + "- \t" * 2000 + "x\n" + "y\n" * 4000 + "<script>1</script>", "html_not_allowed"),
        ("- " * 4000 + "- - -", None),
    ):
        with _gc_paused():
            t0_div = time.process_time()
            assert check_markdown_safe_violation(direct_bomb) == expected_code
            elapsed_ms = (time.process_time() - t0_div) * 1000.0
        assert elapsed_ms < 50.0, f"direct markdown_safe case took {elapsed_ms:.2f}ms CPU (len={len(direct_bomb)})"
    assert check_markdown_safe_violation("[`<img src=x>`](javascript:x [b] `<script>1</script>\n\n[b]: ok") == "html_not_allowed"

    for payload, expected_err in (
        ("a <a x=\u00a0b>", "html_not_allowed"),
        ("a <a x=\u00a0>", "html_not_allowed"),
        ("<a x=\u00a0>", "html_not_allowed"),
        ("<a x=\u00a0b>", "html_not_allowed"),
        ("a <a x=1\u00a02>", "html_not_allowed"),
        ("a <a x=\u00a0\u00a0y=1>", "html_not_allowed"),
        ("a <!----> b", "html_not_allowed"),
        ("a <a x=\u00a0y=1>", None),
        ("a <a x= >", None),
        ("<a x= >", None),
        ("a <!-- a ---> b", None),
    ):
        if expected_err is None:
            assert ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())["root"]["value"] == payload
        else:
            with pytest.raises(ui_doc.UiDocError) as exc:
                ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": payload}}, routes=(), tools=())
            assert exc.value.code == expected_err, payload
