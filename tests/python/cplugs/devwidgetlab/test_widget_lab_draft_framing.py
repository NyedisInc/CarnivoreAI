
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import security_headers as sh
from src.cplugs.host import developer_mode
from src.cplugs.devwidgetlab.drafts import create, preview
from src.cplugs.sdk import signed_links
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import host_app  # noqa: F401
from tests.python.cplugs.owner import turn_on

FRAME = f"{sh.DRAFT_HARNESS_PREFIX}some-ticket/index.html"


def _ancestors(path: str) -> str:
    return next(part.split(" ", 1)[1] for part in sh.csp_for_path(path).rstrip(";").split("; ") if part.startswith("frame-ancestors"))


@pytest.mark.parametrize("path", [
    "/", "/static/index.html", "/static/popout.html/", "/api/v1/cplugs/devwidgetlab/drafts", "/api/v1/cplugs/devwidgetlab/status",
    "/api/v1/cplugs/devwidgetlab/draft-harness", "/api/v1/cplugs/devwidgetlab/draft-harnessx/t/index.html", "/api/v1/cplugs/devwidgetlab/../draft-harness/t",
    "/api/v1/cplugs/huddle/artifact-view/t", "/static/dist/widget-lab/index.html/", "/static/dist/widget-lab/draft.js",
])
def test_every_other_path_stays_none_even_while_drafts_are_framable(monkeypatch, path: str) -> None:
    monkeypatch.setattr(sh, "draft_framing_allowed", lambda: True)
    assert _ancestors(path) == "'none'"


def test_the_exact_frameable_list_is_unchanged() -> None:
    assert sh.SELF_FRAMEABLE_PATHS == frozenset({"/static/popout.html", sh.WIDGET_LAB_PATH})


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
