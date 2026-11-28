
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import security_headers as sh
from src.plugins.host import developer_mode
from src.plugins.devwidgetlab.drafts import create, preview
from src.plugins.sdk import signed_links
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import host_app  # noqa: F401
from tests.python.cplugs.owner import turn_on

FRAME = "/api/v1/cplugs/devwidgetlab/draft-harness/some-ticket/index.html"


def _ancestors(path: str) -> str:
    return next(part.split(" ", 1)[1] for part in sh.csp_for_path(path).rstrip(";").split("; ") if part.startswith("frame-ancestors"))


@pytest.mark.parametrize("path", [
    "/", "/static/index.html", "/static/popout.html/", "/api/v1/cplugs/devwidgetlab/drafts", "/api/v1/cplugs/devwidgetlab/status",
    "/api/v1/cplugs/devwidgetlab/draft-harness", "/api/v1/cplugs/devwidgetlab/draft-harnessx/t/index.html", "/api/v1/cplugs/devwidgetlab/../draft-harness/t",
    "/api/v1/cplugs/devwidgetlab/draft-harness/../secrets", "/api/v1/cplugs/devwidgetlab/draft-harness//t", "/api/v1/cplugs/devwidgetlab/draft-harness\\t",
    "/api/v1/cplugs/devwidgetlab/draft-harness/%2e%2e/secrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/%2E%2E/secrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/%2f/secrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/%5csecrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/%252e%252e/secrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/./secrets",
    "/api/v1/cplugs/devwidgetlab/draft-harness/.",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/./index.html",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/.",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1//index.html",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/",
    "/api/v1/cplugs/devwidgetlab%2fdraft-harness/ticket-1/index.html",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/index.html?x=1",
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket\x00/index.html",
    "/api/v1/cplugs/huddle/artifact-view/t", "/static/dist/widget-lab/index.html/", "/static/dist/widget-lab/draft.js",
])
def test_every_other_path_stays_none_even_while_drafts_are_framable(monkeypatch, path: str) -> None:
    monkeypatch.setattr(sh, "dev_prefix_framing_allowed", lambda _plugin_id: True)
    assert _ancestors(path) == "'none'"


def test_the_exact_frameable_list_is_unchanged() -> None:
    assert sh.SELF_FRAMEABLE_PATHS == frozenset({"/static/popout.html", sh.WIDGET_LAB_PATH})
    assert ("/api/v1/cplugs/devwidgetlab/draft-harness/", "devwidgetlab") in sh.dev_frameable_entries()


def test_a_served_draft_page_carries_the_framing_header_while_developer_mode_is_on(host_app, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
    app, host = host_app
    turn_on(host, "devwidgetlab")

    @app.middleware("http")
    async def stamp(request, call_next):
        response = await call_next(request)
        sh.stamp_security_headers(response.headers, request.url.path)
        return response

    storage = host.state_dir / "cplugs" / "devwidgetlab"
    made = create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    site = storage / "drafts" / made["slug"] / "build" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<html>draft</html>")
    path = preview.mint_ticket(made["slug"])["path"]
    with TestClient(app) as client:
        framed = client.get(path)
        assert framed.status_code == 200 and "<html>draft" in framed.text and "frame-ancestors 'self'" in framed.headers["content-security-policy"]
        monkeypatch.setattr(developer_mode, "is_on", lambda: False)
        refused = client.get(path)
        assert "frame-ancestors 'none'" in refused.headers["content-security-policy"]


@pytest.mark.parametrize("path", [
    "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/index.html",
    "/api/v1/cplugs/devwidgetlab/draft-harness/",
    "/api/v1/cplugs/devwidgetlab/draft-harness/my-draft.1760000000.AbC_123-xyz/index.html",
])
def test_valid_draft_harness_paths_stay_self_frameable(monkeypatch, path: str) -> None:
    monkeypatch.setattr(sh, "dev_prefix_framing_allowed", lambda _plugin_id: True)
    assert _ancestors(path) == "'self'"


def test_dev_frameable_entries_rejects_dot_and_encoded_prefixes(monkeypatch) -> None:
    from src.plugins.host import runtime

    bad_manifest = SimpleNamespace(
        tier="dev",
        renamed_from="",
        ui_meta={"dev_frame_prefixes": ["/./", "/a/./b/", "/%2e%2e/", "/%2f/", "/a\\b/", "/valid-preview/"]},
    )
    monkeypatch.setattr(runtime, "definitions", lambda: [SimpleNamespace(id="synthdev", manifest=bad_manifest)])
    assert sh.dev_frameable_entries() == (("/api/v1/cplugs/synthdev/valid-preview/", "synthdev"),)


def test_stamp_security_headers_fails_closed_on_encoded_raw_path(monkeypatch) -> None:
    from starlette.datastructures import MutableHeaders

    monkeypatch.setattr(sh, "dev_prefix_framing_allowed", lambda _plugin_id: True)
    decoded_path = "/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/index.html"

    rejected = MutableHeaders()
    sh.stamp_security_headers(
        rejected,
        decoded_path,
        raw_path=b"/api/v1/cplugs/devwidgetlab/draft-harness%2fticket-1/index.html",
    )
    assert "frame-ancestors 'none'" in rejected["Content-Security-Policy"]

    accepted = MutableHeaders()
    sh.stamp_security_headers(
        accepted,
        decoded_path,
        raw_path=b"/api/v1/cplugs/devwidgetlab/draft-harness/ticket-1/index.html",
    )
    assert "frame-ancestors 'self'" in accepted["Content-Security-Policy"]
