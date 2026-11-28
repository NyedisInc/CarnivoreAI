
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from src.api.auth import require_auth
from src.core.api_keys import fence
from src.core.federation import peer_forward
from src.core.mcp_usage import old_names as core_old_names, store as usage_store
from src.plugins.host import identity, renamed, runtime
from src.plugins.sdk import manifest as m, old_names, renamed_from as rf
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.routing import cplug_router
from src.security_headers import dev_frameable_prefixes
from tests.python.cplugs.renamed_world import LIMIT, World, build, definitions, raw_manifest


@pytest.fixture(autouse=True)
def _isolate_old_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(old_names, "_declared", {k: set(v) for k, v in old_names._declared.items()})


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return build(tmp_path, monkeypatch)


@pytest.mark.asyncio
async def test_the_old_prefix_runs_the_real_handler_for_a_client_that_never_follows_a_redirect(world: World) -> None:
    world.app.dependency_overrides[require_auth] = lambda: True
    async with world.client() as client:
        old = await client.post("/api/v1/cplugs/beta/x?k=1", json={"a": 1})
        assert old.status_code == 200 and old.json() == {"got": {"a": 1}} and "location" not in old.headers
        encoded = await client.post("/api/v1/cplugs/%62eta/x", json={"a": 2})
        assert encoded.status_code == 200 and encoded.json() == {"got": {"a": 2}}
        assert (await client.post("/api/v1/cplugs/beta/nope", json={})).status_code == 404
        assert (await client.get("/api/v1/cplugs/beta/x")).status_code == 405
    assert core_old_names.flush(usage_store.get_store()) == 2
    rows = usage_store.get_store().old_names_between("0000-01-01", "9999-12-31")
    assert [(kind, name, via, calls) for _day, kind, name, via, calls in rows] == [("route", "POST /cplugs/beta/x", "route", 2)]
    assert old_names.declared()["route"] == ["GET /cplugs/beta/p", "POST /cplugs/beta/limited", "POST /cplugs/beta/x"]


@pytest.mark.asyncio
async def test_auth_is_identical_at_both_prefixes(world: World) -> None:
    async with world.client() as anonymous:
        assert (await anonymous.post("/api/v1/cplugs/alpha/x", json={"a": 1})).status_code == 401
        assert (await anonymous.post("/api/v1/cplugs/beta/x", json={"a": 1})).status_code == 401
        assert (await anonymous.get("/api/v1/cplugs/beta/p")).json() == {"public": "yes"}
    alpha = runtime.find("alpha")
    targets = {(r.path, tuple(sorted(r.methods))): r for r in alpha.router.routes if isinstance(r, APIRoute)}
    aliases = [((r.path, tuple(sorted(r.methods))), r) for r in renamed.alias_router(alpha).routes]
    assert len(aliases) == len(targets) == 3
    for (path, methods), alias in aliases:
        target = targets[(path.replace("/cplugs/beta/", "/cplugs/alpha/", 1), methods)]
        assert alias.endpoint is target.endpoint, path
        assert [d.dependency for d in alias.dependencies[:-1]] == [d.dependency for d in target.dependencies], path
        assert alias.dependencies[-1].dependency.__name__ == "count", path
        assert type(alias) is type(target) and alias.strict_content_type == target.strict_content_type, path


class _BoundedRoute(APIRoute):
    pass


def test_an_alias_keeps_a_custom_route_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset({"beta"}))
    monkeypatch.setattr(old_names, "_declared", {})
    router = cplug_router("alpha")
    router.route_class = _BoundedRoute

    @router.post("/b")
    async def bounded() -> dict:
        """A route of the custom class. Output: dict."""
        return {}

    alpha = CplugDefinition(manifest=m.parse_manifest(raw_manifest("alpha", surfaces={"routes": True}, renamed_from="beta")), router=router)
    (alias,) = renamed.alias_router(alpha).routes
    assert type(alias) is _BoundedRoute and alias.path == "/cplugs/beta/b"


@pytest.mark.asyncio
async def test_the_rate_limiter_applies_at_the_old_prefix(world: World) -> None:
    async with world.client() as anonymous:
        answers = [(await anonymous.post("/api/v1/cplugs/beta/limited")).status_code for _ in range(LIMIT + 1)]
    assert answers == [200] * LIMIT + [429]


def test_a_renamed_plugin_with_no_router_has_no_alias_router_and_its_old_id_still_resolves(world: World) -> None:
    bare = CplugDefinition(manifest=m.parse_manifest(raw_manifest("delta", renamed_from="beta")))
    assert renamed.alias_router(bare) is None
    assert runtime.canonical_id("beta") == "alpha" and runtime.canonical_id("alpha") == "alpha" and runtime.canonical_id("zed") == "zed"


def test_find_is_exact_and_requires_resolve_the_old_id(world: World) -> None:
    assert runtime.find("beta") is None and runtime.find("alpha").id == "alpha"
    assert runtime.find("gamma").manifest.requires == ("alpha",)


@pytest.mark.parametrize("bad", ["alpha", "Beta", "be-ta", "b", "core", 7])
def test_an_invalid_renamed_from_is_refused_by_the_validator(bad: Any) -> None:
    with pytest.raises(m.ManifestError, match="renamed_from"):
        m.parse_manifest(raw_manifest("alpha", renamed_from=bad))


def test_a_renamed_from_naming_a_shipped_plugin_taken_twice_unreserved_or_a_host_word_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset({"beta", "restart"}))
    alpha, gamma = definitions([])
    shipped = CplugDefinition(manifest=m.parse_manifest(raw_manifest("beta")))
    with pytest.raises(runtime.RegistryError, match="renamed_from beta is also a shipped plugin"):
        runtime.check_definitions((alpha, gamma, shipped))
    twice = CplugDefinition(manifest=m.parse_manifest(raw_manifest("delta", renamed_from="beta")))
    with pytest.raises(runtime.RegistryError, match="beta"):
        runtime.check_definitions((alpha, gamma, twice))
    word = CplugDefinition(manifest=m.parse_manifest(raw_manifest("delta", renamed_from="restart")))
    with pytest.raises(runtime.RegistryError, match="host word"):
        runtime.check_definitions((word,))
    loose = CplugDefinition(manifest=m.parse_manifest(raw_manifest("delta", renamed_from="omega")))
    with pytest.raises(runtime.RegistryError, match="reserved forever"):
        runtime.check_definitions((loose,))
    with pytest.raises(m.ManifestError, match="itself"):
        m.parse_manifest(raw_manifest("alpha", renamed_from="beta", requires=["beta"]))


def test_old_names_are_accepted_only_through_renamed_from_keeps() -> None:
    old_keys = {"name_key": "cplug.beta.name", "description_key": "cplug.beta.description", "owns": {"strings": ["cplug.beta."]}}
    widget = {"surfaces": {"widgets": ["beta.chat"]}, "widgets": {"beta.chat": {"instancing": "per-target", "fits": {"sizes": ["medium"]}}}}
    kept = m.parse_manifest(raw_manifest("alpha", renamed_from="beta", renamed_from_keeps=["strings", "widgets"], **old_keys, **widget))
    assert kept.owns.strings == ("cplug.beta.",) and kept.renamed_from_keeps == ("strings", "widgets")
    assert [rf.widget_id(kept.id, rf.kept_old_id(kept.renamed_from, kept.renamed_from_keeps, rf.KEEP_WIDGETS), n) for n in kept.widgets] == ["beta.chat"]
    assert m.parse_manifest(raw_manifest("alpha", renamed_from="beta", renamed_from_keeps=["widgets"], **widget)).renamed_from == "beta"
    for extra, keeps in ((old_keys, ["widgets"]), (widget, ["strings"]), (old_keys, None), (widget, None)):
        with pytest.raises(m.ManifestError):
            m.parse_manifest(raw_manifest("alpha", renamed_from="beta", **({"renamed_from_keeps": keeps} if keeps else {}), **extra))
        with pytest.raises(m.ManifestError):
            m.parse_manifest(raw_manifest("alpha", **extra))
    for bad in (["strings", "strings"], ["routes"], "strings"):
        with pytest.raises(m.ManifestError, match="renamed_from_keeps"):
            m.parse_manifest(raw_manifest("alpha", renamed_from="beta", renamed_from_keeps=bad))
    with pytest.raises(m.ManifestError, match="needs renamed_from"):
        m.parse_manifest(raw_manifest("alpha", renamed_from_keeps=["strings"]))


def _security_paths() -> list:
    return [p for p, _why in fence.FENCED] + list(dev_frameable_prefixes()) + [r.path for r in peer_forward.TABLE]


def test_path_keyed_security_tables_name_both_prefixes_of_every_renamed_plugin() -> None:
    assert renamed.prefix_table_gaps(runtime.definitions(), _security_paths()) == []


def test_the_security_table_check_goes_red_on_a_row_with_only_one_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset({"beta"}))
    alpha, _gamma = definitions([])
    assert renamed.prefix_table_gaps((alpha,), ["/api/v1/cplugs/alpha/public", "/cplugs/beta/q", "/cplugs/alphabet/x"]) == [
        "/api/v1/cplugs/alpha/public needs /api/v1/cplugs/beta/public", "/cplugs/beta/q needs /cplugs/alpha/q"]
    assert renamed.prefix_table_gaps((alpha,), ["/cplugs/alpha/q", "/cplugs/beta/q"]) == []
