
from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.db_migration import ensure_db_migrated
from src.plugins.host import identity, runtime, sidecar_view
from src.plugins.host.plugin_manifest import SidecarManifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.manifest import Manifest, NetworkDecl, Surfaces
from src.security_headers import build_view_csp
from tests.python.api_keys.conftest import bearer, owner_jwt  # noqa: F401


def test_carnivore_frame_css_has_zero_raw_values_and_tokens_only() -> None:
    css_path = Path("src/plugins/host/carnivore_frame.css")
    text = css_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) < 300
    assert "--oc-ground-page" in text
    assert "--oc-text-primary" in text
    assert "font-weight" not in text
    assert "#" not in text
    assert "px" not in text
    assert "rem" not in text
    assert "rgb(" not in text


def test_inject_frame_css_idempotent() -> None:
    with_head = b"<html><head><title>x</title></head><body>hi</body></html>"
    injected = sidecar_view._inject_frame_css(with_head)
    assert injected.count(b"carnivore-frame.css") == 1
    assert b'<head><link rel="stylesheet" href="carnivore-frame.css"><title>x</title>' in injected

    already = b'<head><link rel="stylesheet" href="carnivore-frame.css"></head><body>ok</body>'
    assert sidecar_view._inject_frame_css(already) == already

    comment_bypass = b"<html><head><!-- carnivore-frame.css --></head><body>hi</body></html>"
    injected_comment = sidecar_view._inject_frame_css(comment_bypass)
    assert b'<head><link rel="stylesheet" href="carnivore-frame.css"><!-- carnivore-frame.css -->' in injected_comment

    script_bypass = b'<html><head><script>const x = "carnivore-frame.css";</script></head><body>hi</body></html>'
    injected_script = sidecar_view._inject_frame_css(script_bypass)
    assert b'<head><link rel="stylesheet" href="carnivore-frame.css"><script>' in injected_script


def test_inject_frame_css_ignores_tags_in_leading_comments_and_handles_doctype_and_uppercase() -> None:
    leading_comment = b"<!-- <head> --><html><head></head><body>x</body></html>"
    assert (
        sidecar_view._inject_frame_css(leading_comment)
        == b'<!-- <head> --><html><head><link rel="stylesheet" href="carnivore-frame.css"></head><body>x</body></html>'
    )

    commented_html_and_head = b"<!-- <html><head></head> --><!doctype html><html><body>x</body></html>"
    assert (
        sidecar_view._inject_frame_css(commented_html_and_head)
        == b'<!-- <html><head></head> --><!doctype html><html><head><link rel="stylesheet" href="carnivore-frame.css"></head><body>x</body></html>'
    )

    doctype_no_head = b"<!doctype html><html><body>x</body></html>"
    assert (
        sidecar_view._inject_frame_css(doctype_no_head)
        == b'<!doctype html><html><head><link rel="stylesheet" href="carnivore-frame.css"></head><body>x</body></html>'
    )

    uppercase_head = b'<HTML><HEAD lang="en"></HEAD><BODY>x</BODY></HTML>'
    assert (
        sidecar_view._inject_frame_css(uppercase_head)
        == b'<HTML><HEAD lang="en"><link rel="stylesheet" href="carnivore-frame.css"></HEAD><BODY>x</BODY></HTML>'
    )

    comment_only_head = b"<!-- <head> --><body>x</body>"
    assert (
        sidecar_view._inject_frame_css(comment_only_head)
        == b'<link rel="stylesheet" href="carnivore-frame.css">\n<!-- <head> --><body>x</body>'
    )


def test_inject_frame_css_skips_script_and_style_tags_and_malformed_comments() -> None:
    import time

    script_head = b"<html><script>const s = '<head>';</script><head></head></html>"
    assert (
        sidecar_view._inject_frame_css(script_head)
        == b'<html><script>const s = \'<head>\';</script><head><link rel="stylesheet" href="carnivore-frame.css"></head></html>'
    )

    style_head = b"<html><style>.x::before { content: '<head>'; }</style><head></head></html>"
    assert (
        sidecar_view._inject_frame_css(style_head)
        == b'<html><style>.x::before { content: \'<head>\'; }</style><head><link rel="stylesheet" href="carnivore-frame.css"></head></html>'
    )

    script_only_fake_tags = b"<script>const a = '<html><head>';</script><body>x</body>"
    assert (
        sidecar_view._inject_frame_css(script_only_fake_tags)
        == b'<link rel="stylesheet" href="carnivore-frame.css">\n<script>const a = \'<html><head>\';</script><body>x</body>'
    )

    unclosed_comments = ("<!--" * 20000 + "<head></head>").encode("utf-8")
    t0 = time.monotonic()
    res = sidecar_view._inject_frame_css(unclosed_comments)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2
    assert res.startswith(b'<link rel="stylesheet" href="carnivore-frame.css">\n')


def test_inject_frame_css_handles_turkish_capital_i_dot_above() -> None:
    html = (
        "<html><!-- \u0130\u0130\u0130 -->"
        "<script>const s = '<head>'; // \u0130\u0130</script>"
        "<style>.a::before { content: '<head>'; } /* \u0130 */</style>"
        "<head><title>\u0130stanbul</title></head><body>ok</body></html>"
    ).encode("utf-8")
    injected = sidecar_view._inject_frame_css(html).decode("utf-8")
    assert injected.count("carnivore-frame.css") == 1
    assert "<head><link rel=\"stylesheet\" href=\"carnivore-frame.css\"><title>\u0130stanbul</title></head>" in injected
    assert "<script>const s = '<head>'; // \u0130\u0130</script>" in injected


def test_cplug_row_serializes_compiled_builtin_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.host import routes

    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    app_ns = SimpleNamespace()
    host = runtime.Host(state, app_ns)
    monkeypatch.setattr(routes.owner_state, "get", lambda _s, _m: SimpleNamespace(enabled=True, grants=(), digest="", settings={}, revision=1))
    monkeypatch.setattr(routes.gate, "blocked_by", lambda _id, _s: ())
    monkeypatch.setattr(routes.dependencies, "dependency_view", lambda _m, _s: {})

    with_views = CplugDefinition(
        manifest=Manifest(
            id="builtview",
            name_key="cplug.builtview.name",
            description_key="cplug.builtview.description",
            version="1.0.0",
            icon="plug",
            author="Carnivore",
            min_app_version="1.0.0",
            tier="builtin",
            default_enabled=True,
            permissions=(),
            surfaces=Surfaces(),
            views=({"name": "dash", "surfaces": ["panel"], "fits": {"sizes": ["large"]}, "files": {"index.html"}},),
        ),
        code_root=tmp_path,
    )
    without_views = CplugDefinition(
        manifest=Manifest(
            id="plainbuiltin",
            name_key="cplug.plainbuiltin.name",
            description_key="cplug.plainbuiltin.description",
            version="1.0.0",
            icon="plug",
            author="Carnivore",
            min_app_version="1.0.0",
            tier="builtin",
            default_enabled=True,
            permissions=(),
            surfaces=Surfaces(),
        ),
    )
    row_with = routes.cplug_row(host, with_views)
    row_without = routes.cplug_row(host, without_views)
    assert row_with["runtime"] == "compiled"
    assert row_with["views"] == [{"name": "dash", "surfaces": ["panel"], "fits": {"sizes": ["large"]}}]
    assert row_without["views"] is None


def test_served_carnivore_frame_css_defines_root_oc_vars_for_opaque_origins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import re

    frame_text = Path("src/plugins/host/carnivore_frame.css").read_text(encoding="utf-8")
    referenced = set(re.findall(r"--oc-[a-z0-9-]+", frame_text))
    assert len(referenced) >= 34

    served_tokens = sidecar_view._read_frame_css().decode("utf-8")
    assert ":root {" in served_tokens
    defined_tokens = set(re.findall(r"^\s*(--oc-[a-z0-9-]+)\s*:", served_tokens, re.M))
    missing = referenced - defined_tokens
    assert not missing, f"missing --oc-* definitions in served CSS: {sorted(missing)}"
    assert "--oc-ground-content" in defined_tokens

    monkeypatch.setattr(sidecar_view, "_TOKENS_CSS_PATH", tmp_path / "missing-tokens.css")
    served_dist = sidecar_view._read_frame_css().decode("utf-8")
    defined_dist = set(re.findall(r"^\s*(--oc-[a-z0-9-]+)\s*:", served_dist, re.M))
    assert not (referenced - defined_dist)
    assert "--oc-ground-content" in defined_dist


@pytest.mark.parametrize(
    ("tier_kind", "item_id", "tier"),
    [
        ("builtin", None, "builtin"),
        ("warez_verified", "acme/viewplug", "catalog"),
        ("unverified_github", "github/viewplug", identity.TIER_UNVERIFIED_GITHUB),
        ("local_dev", "local/viewplug", "local"),
    ],
)
def test_all_visible_tiers_serve_sandboxed_views_with_frame_css(
    tmp_path: Path,
    owner_jwt,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tier_kind: str,
    item_id: str | None,
    tier: str,
) -> None:
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    code_root = tmp_path / "code" / "viewplug"
    view_dir = code_root / "views" / "main"
    view_dir.mkdir(parents=True)
    (view_dir / "index.html").write_text("<html><head></head><body><button>Go</button></body></html>", encoding="utf-8")

    view_entry = {"name": "main", "surfaces": ["panel"], "fits": "fill", "files": {"index.html"}}
    if tier_kind == "builtin":
        manifest = Manifest(
            id="viewplug",
            name_key="cplug.viewplug.name",
            description_key="cplug.viewplug.description",
            version="1.0.0",
            icon="plug",
            author="Carnivore",
            min_app_version="1.0.0",
            tier="builtin",
            default_enabled=True,
            permissions=(),
            surfaces=Surfaces(),
            views=(view_entry,),
        )
        defn = CplugDefinition(manifest=manifest, code_root=code_root)
    else:
        manifest = SidecarManifest(
            id="viewplug",
            name="View Plug",
            description="View",
            version="1.0.0",
            entry="main.py",
            tools=(),
            permissions=(),
            network=NetworkDecl(),
            author="Acme",
            tier=tier,
            code_digest="deadbeef",
            views=(view_entry,),
        )
        defn = SidecarDefinition(manifest, item_id or "acme/viewplug", "uuid-viewplug", code_root, tmp_path / "data", "KEY1")

    class _Sup:
        def state(self, _pid: str) -> str:
            return "running"

        def is_paused(self, _pid: str) -> bool:
            return False

    live = SimpleNamespace(
        supervisor=_Sup(),
        safe_mode=lambda: {"env": False, "switch": False, "route": False},
    )
    fake_host = runtime.Host(state, app)
    monkeypatch.setattr(fake_host, "enabled", lambda _pid: True)
    monkeypatch.setattr(fake_host, "sidecar_runtime", lambda: live)
    monkeypatch.setattr(fake_host, "install_key", lambda _pid: "uuid-viewplug")

    monkeypatch.setattr("src.plugins.host.sidecar_view.runtime.find", lambda cid: defn if cid == "viewplug" else None)
    monkeypatch.setattr("src.plugins.host.sidecar_view.runtime.hidden", lambda _d: False)
    app.state.cplugs_host = fake_host

    try:
        with TestClient(app) as tc:
            r_t = tc.post("/api/v1/cplugs/viewplug/view/main/ticket", headers=bearer(owner_jwt))
            assert r_t.status_code == 200, r_t.text
            idx_path = r_t.json()["path"]
            base = idx_path.rsplit("/", 1)[0] + "/"

            r_html = tc.get(idx_path)
            assert r_html.status_code == 200
            assert b'<link rel="stylesheet" href="carnivore-frame.css">' in r_html.content
            expected_csp = build_view_csp(f"http://testserver{base}")
            assert r_html.headers["content-security-policy"] == expected_csp

            r_css = tc.get(base + "carnivore-frame.css")
            assert r_css.status_code == 200
            assert r_css.headers["content-type"].startswith("text/css")
            assert r_css.headers["content-security-policy"] == expected_csp
            assert r_css.headers["x-content-type-options"] == "nosniff"
            assert r_css.headers["cache-control"] == "no-store"
            assert r_css.headers["cross-origin-resource-policy"] == "cross-origin"
            assert "x-carnivore-own-policy" not in r_css.headers
            assert ":root {" in r_css.text
            assert "--oc-ground-page:" in r_css.text
            assert "--oc-fs-body:" in r_css.text
            assert "--oc-space-4:" in r_css.text
    finally:
        if hasattr(app.state, "cplugs_host"):
            delattr(app.state, "cplugs_host")
