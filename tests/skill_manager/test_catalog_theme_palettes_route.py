
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api import auth as auth_module
from src.api import catalog_theme_palette_routes as routes
from src.core.catalog import theme_palettes
from src.core.skills.contents_view import ContentsView

D1, D2, D3, D4 = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _version(digest: str) -> SimpleNamespace:
    return SimpleNamespace(v="1.0.0", digest=digest)


def _item(item_id: str, kind: str, digest: str) -> SimpleNamespace:
    v = _version(digest)
    return SimpleNamespace(id=item_id, kind=kind, latest="1.0.0", versions=[v])


def _manifest(**css: str) -> str:
    return json.dumps({"cssVars": css, "xterm": {"background": "#010203"}})


class Harness:

    def __init__(self, tmp_path, items, views: Dict[str, Any]) -> None:
        self.calls: List[str] = []
        self.live = 0
        self.peak = 0
        self.views = views
        snapshot = SimpleNamespace(verified=SimpleNamespace(items=items, serial=1))
        self.snapshot = snapshot
        cache = SimpleNamespace(get=self._get(snapshot))
        services = SimpleNamespace(
            catalog=SimpleNamespace(index_cache=cache),
            settings_reader=SimpleNamespace(state_dir=lambda: tmp_path),
        )
        self.app = FastAPI()
        self.app.state.services = services
        self.app.include_router(routes.router)

    @staticmethod
    def _get(snapshot):
        async def get():
            return snapshot
        return get

    async def read(self, services, item, version):
        self.calls.append(item.id)
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(0.02)
            answer = self.views[item.id]
            if isinstance(answer, Exception):
                raise answer
            return answer
        finally:
            self.live -= 1


def _view(digest: str, text: str) -> ContentsView:
    return ContentsView(digest, text, False, (), 0)


@pytest.fixture
def make(tmp_path, monkeypatch):
    theme_palettes._inflight.clear()
    theme_palettes._refused.clear()
    monkeypatch.setattr(theme_palettes, "_serial", None)
    monkeypatch.setattr(theme_palettes, "_pruned_serial", None)

    def build(items, views, authed=True):
        h = Harness(tmp_path, items, views)
        monkeypatch.setattr(
            routes, "view_of_version", lambda services, item, version: h.read(services, item, version)
        )
        if authed:
            h.app.dependency_overrides[auth_module.require_auth] = lambda: None
        return h, TestClient(h.app)

    return build


def test_unauthenticated_is_401(make):
    h, client = make([], {}, authed=False)
    assert client.get("/catalog/theme-palettes").status_code == 401


def test_only_trusted_themes_and_unsafe_values_are_dropped(make):
    items = [_item("n/snes", "theme", D1), _item("n/sme", "skill", D2)]
    text = _manifest(**{
        "--color-bg": "#112233",
        "--color-accent": "url(http://evil/x)",
        "--color-fg": "var(--x)",
        "--color-danger": "#fff;}body{display:none",
        "--color-success": "rgba(1, 2, 3, 0.5)",
    })
    h, client = make(items, {"n/snes": _view(D1, text), "n/sme": _view(D2, text)})
    body = client.get("/catalog/theme-palettes").json()
    assert list(body["items"]) == ["n/snes"]
    assert h.calls == ["n/snes"]
    css = body["items"]["n/snes"]["cssVars"]
    assert css == {"--color-bg": "#112233", "--color-success": "rgba(1, 2, 3, 0.5)"}
    assert body["items"]["n/snes"]["xterm"] == {"background": "#010203"}
    assert body["pending"] == []


def test_a_digest_mismatch_gives_no_entry_and_no_pending(make):
    refused = HTTPException(409, {"code": "digest_mismatch", "detail": "x"})
    items = [_item("n/a", "theme", D1), _item("n/b", "theme", D2)]
    h, client = make(items, {"n/a": refused, "n/b": _view(D3, _manifest(**{"--color-bg": "#000"}))})
    body = client.get("/catalog/theme-palettes").json()
    assert body == {"items": {}, "pending": []}


def test_staging_busy_is_pending_and_retried_by_the_next_read(make):
    busy = HTTPException(409, {"code": "staging_busy", "detail": "full"})
    h, client = make([_item("n/a", "theme", D1)], {"n/a": busy})
    assert client.get("/catalog/theme-palettes").json() == {"items": {}, "pending": ["n/a"]}
    h.views["n/a"] = _view(D1, _manifest(**{"--color-bg": "#000"}))
    again = client.get("/catalog/theme-palettes").json()
    assert list(again["items"]) == ["n/a"] and again["pending"] == []


def test_the_fetcher_never_runs_more_than_two_at_once(make):
    ids = [f"n/t{i}" for i in range(6)]
    digests = [c * 64 for c in "01234a"]
    items = [_item(i, "theme", d) for i, d in zip(ids, digests)]
    views = {i: _view(d, _manifest(**{"--color-bg": "#000"})) for i, d in zip(ids, digests)}
    h, client = make(items, views)
    body = client.get("/catalog/theme-palettes").json()
    assert len(body["items"]) == 6
    assert h.peak == 2


def test_a_second_call_is_served_from_the_digest_cache(make):
    h, client = make([_item("n/a", "theme", D4)], {"n/a": _view(D4, _manifest(**{"--color-bg": "#000"}))})
    first = client.get("/catalog/theme-palettes").json()
    second = client.get("/catalog/theme-palettes").json()
    assert first == second and list(first["items"]) == ["n/a"]
    assert h.calls == ["n/a"]


def test_one_bundle_that_raises_leaves_the_other_palettes(make):
    items = [_item("n/bad", "theme", D1), _item("n/ok", "theme", D2)]
    h, client = make(items, {
        "n/bad": OSError("disk gone"),
        "n/ok": _view(D2, _manifest(**{"--color-bg": "#000"})),
    })
    resp = client.get("/catalog/theme-palettes")
    assert resp.status_code == 200
    assert list(resp.json()["items"]) == ["n/ok"] and resp.json()["pending"] == []


def test_a_refused_digest_is_not_refetched_until_the_serial_moves(make):
    refused = HTTPException(409, {"code": "digest_mismatch", "detail": "x"})
    h, client = make([_item("n/a", "theme", D1)], {"n/a": refused})
    for _ in range(2):
        assert client.get("/catalog/theme-palettes").json() == {"items": {}, "pending": []}
    assert h.calls == ["n/a"]
    h.snapshot.verified.serial = 2
    client.get("/catalog/theme-palettes")
    assert h.calls == ["n/a", "n/a"]


def test_a_busy_or_transport_failure_is_not_remembered(make):
    h, client = make([_item("n/a", "theme", D1)], {"n/a": HTTPException(502, {"code": "fetch_failed"})})
    client.get("/catalog/theme-palettes")
    client.get("/catalog/theme-palettes")
    assert h.calls == ["n/a", "n/a"]


def test_a_tampered_cache_value_is_a_miss_and_stale_files_are_pruned(make, tmp_path):
    h, client = make([_item("n/a", "theme", D1)], {"n/a": _view(D1, _manifest(**{"--color-bg": "#000"}))})
    client.get("/catalog/theme-palettes")
    cache_dir = tmp_path / "catalog_theme_palettes"
    path = cache_dir / f"{D1}.json"
    data = json.loads(path.read_text())
    data["cssVars"]["--color-bg"] = "url(http://evil/x)"
    path.write_text(json.dumps(data))
    stale = cache_dir / f"{D3}.json"
    stale.write_text("{}")
    h.snapshot.verified.serial = 2
    body = client.get("/catalog/theme-palettes").json()
    assert body["items"]["n/a"]["cssVars"] == {"--color-bg": "#000"}
    assert h.calls == ["n/a", "n/a"]
    assert not stale.exists() and path.exists()
