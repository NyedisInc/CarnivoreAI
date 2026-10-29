
import pytest
from fastapi import APIRouter

from src.cplugs.host import identity, routes
from src.cplugs.sdk.routing import cplug_router


def _fixture_router(prefix: str, method: str, path: str) -> APIRouter:
    r = APIRouter(prefix=prefix)
    r.add_api_route(path, lambda: None, methods=[method])
    return r


def test_host_router_is_mounted_before_every_plugin_router():
    mounted = [r.original_router for r in routes.build_router().routes]
    assert mounted[0] is routes.host_router
    assert len(mounted) > 1 and routes.host_router not in mounted[1:]


def test_plugin_route_can_never_shadow_a_host_route():
    with pytest.raises(ValueError):
        routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/evil", "POST", "/purge"))
    with pytest.raises(ValueError):
        routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/evil", "GET", ""))
    with pytest.raises(ValueError):
        routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/evil/r", "PUT", "/secrets/{name}"))
    routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/evil/r", "PUT", "/lists"))


@pytest.mark.parametrize("method,path", [("PUT", "/{seg}/{name}"), ("PUT", "/{rest:path}")])
def test_param_first_segment_cannot_take_a_reserved_route_name(method, path):
    with pytest.raises(ValueError):
        routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/gh/r", method, path))


def test_plugin_template_that_covers_a_host_path_is_refused():
    with pytest.raises(ValueError):
        routes.assert_no_shadow(routes.host_router, _fixture_router("/cplugs/evil", "POST", "/{x}"))


def test_registry_host_picks_the_layout():
    from src.cplugs.host import runtime
    from src.cplugs.sdk.manifest import TIERS
    assert runtime.router_prefix("huddle", third_party="builtin" not in TIERS) == "/cplugs/huddle"


def test_third_party_router_lives_under_r():
    assert cplug_router("gh", third_party=True).prefix == "/cplugs/gh/r"
    assert cplug_router("huddle").prefix == "/cplugs/huddle"


@pytest.mark.parametrize("name,code", [
    ("core", "name_reserved"), ("state", "name_reserved"), ("r", "name_invalid"), ("slack", "name_reserved"),
    ("huddle", "name_reserved"), ("safe-mode", "name_invalid"), ("my-plug", "name_invalid"), ("A", "name_invalid"),
])
def test_reserved_and_invalid_install_names_are_refused(tmp_path, name, code):
    with pytest.raises(identity.InstallRefused) as exc:
        identity.register_install(tmp_path, name, "acme/x", {"huddle"})
    assert exc.value.code == code
    assert identity.lookup(tmp_path, name) is None


def test_two_installs_never_share_data_or_a_secret(tmp_path):
    a = identity.register_install(tmp_path, "gh", "acme/github", set())
    b = identity.register_install(tmp_path, "gh2", "other/github", set())
    assert a.uuid != b.uuid and len(a.uuid) == 32
    assert identity.data_dir(tmp_path, identity.data_key(a)) != identity.data_dir(tmp_path, identity.data_key(b))
    assert identity.keychain_service(identity.data_key(a)) != identity.keychain_service(identity.data_key(b))
    assert a.name not in str(identity.data_dir(tmp_path, identity.data_key(a)))


def test_removed_name_stays_reserved_to_its_catalog_id_until_purge(tmp_path):
    first = identity.register_install(tmp_path, "gh", "acme/github", set())
    with pytest.raises(identity.InstallRefused) as exc:
        identity.register_install(tmp_path, "gh", "evil/github", set())
    assert exc.value.code == "name_taken"
    assert identity.register_install(tmp_path, "gh", "acme/github", set()) == first
    assert identity.release_install(tmp_path, "gh") is True
    again = identity.register_install(tmp_path, "gh", "evil/github", set())
    assert again.uuid != first.uuid


def test_corrupt_ledger_fails_closed_and_is_never_overwritten(tmp_path):
    identity.register_install(tmp_path, "gh", "acme/github", set())
    identity.register_install(tmp_path, "other", "acme/other", set())
    path = tmp_path / "cplugs" / identity.LEDGER_FILE
    path.write_bytes(path.read_bytes()[:20])
    before = path.read_bytes()
    with pytest.raises(identity.LedgerUnreadable):
        identity.register_install(tmp_path, "gh", "evil/github", set())
    with pytest.raises(identity.LedgerUnreadable):
        identity.release_install(tmp_path, "gh")
    assert path.read_bytes() == before


def test_bad_uuid_row_is_a_corrupt_ledger(tmp_path):
    path = tmp_path / "cplugs" / identity.LEDGER_FILE
    path.parent.mkdir(parents=True)
    path.write_text('{"installs": {"gh": {"uuid": "../../../x", "catalog_id": "a/b"}}}')
    with pytest.raises(identity.LedgerUnreadable):
        identity.lookup(tmp_path, "gh")


def test_install_name_matches_the_plugin_id_pattern_and_keys_are_validated(tmp_path):
    with pytest.raises(identity.InstallRefused) as exc:
        identity.register_install(tmp_path, "a" * 30, "acme/x", set())
    assert exc.value.code == "name_invalid"
    with pytest.raises(ValueError):
        identity.data_dir(tmp_path, "../x")
    with pytest.raises(ValueError):
        identity.data_key(None, "../x")
