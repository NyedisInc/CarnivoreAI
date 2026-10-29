
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ai_routes
from src.api.auth import require_auth
from src.config.byoai import TargetRef
from src.core.byoai import gateway as gateway_module
from src.core.byoai import registry
from src.core.byoai.calllog import CallLog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from tests.python.byoai.test_byoai_routes import FakeKeychain

OWNED = "owned.feature"
SWITCH = {"value": None}


def _override(block):
    stored = SWITCH["value"]
    return stored if isinstance(stored, bool) else OWNED in block.features


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keys = KeyStore(backend=FakeKeychain())
    store = ByoaiStore(config, keys=keys)
    gateway_module.set_gateway(Gateway(store, CallLog(tmp_path), keys))
    monkeypatch.setattr(registry, "DEFAULT", registry.FeatureRegistry())
    SWITCH["value"] = None
    owner = registry.FeatureOwner("addon", "settings.section.addon", "addon", "ai", "addon.ai.override",
                                  override=_override)
    registry.register_feature(OWNED, "chat", "ai.feature.owned", owner=owner)
    registry.register_feature("plain.feature", "chat", "ai.feature.plain")
    app = FastAPI()
    app.include_router(ai_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    yield TestClient(app), store, tmp_path
    gateway_module.set_gateway(None)


def _features(http):
    response = http.get("/api/v1/ai/features")
    assert response.status_code == 200
    return {f["id"]: f for f in response.json()["features"]}


def test_owned_features_carry_the_owner_link_and_hide_while_the_override_is_off(client):
    http, store, state = client
    SWITCH["value"] = False
    rows = _features(http)
    assert rows[OWNED]["owner"] == {"id": "addon", "label_key": "settings.section.addon",
                                    "href": "#settings/addon/ai?highlight=addon.ai.override",
                                    "control": "addon.ai.override", "overridden": False}
    assert rows[OWNED]["hidden"] is True
    assert rows["plain.feature"]["owner"] is None and rows["plain.feature"]["hidden"] is False

    SWITCH["value"] = True
    rows = _features(http)
    assert rows[OWNED]["hidden"] is False and rows[OWNED]["owner"]["overridden"] is True


def test_an_install_that_never_wrote_the_switch_follows_its_route(client):
    http, store, state = client
    assert _features(http)[OWNED]["hidden"] is True
    spark = store.add_connection(preset="ollama", label="mini")
    store.set_feature(OWNED, TargetRef(connection=spark.id, model="m"), expected_revision=store.read().revision)
    row = _features(http)[OWNED]
    assert row["hidden"] is False and row["target"]["connection"] == spark.id


def test_an_owner_whose_switch_cannot_be_read_stays_listed():
    def broken(block):
        raise OSError("unreadable")

    owner = registry.FeatureOwner("x", "k", "general", control="x.override", override=broken)
    view = registry.feature_view(registry.Feature("x.f", "chat", "k", owner=owner), block=None)
    assert view["hidden"] is False and view["owner"]["overridden"] is None
    assert view["owner"]["href"] == "#settings/general?highlight=x.override"


def test_a_plugin_owner_links_to_its_own_pane_not_a_settings_section():
    owner = registry.FeatureOwner("cplug.demo", "k", "plugins", page="#plugins/demo/settings")
    assert owner.href() == "#plugins/demo/settings"
