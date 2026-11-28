
from __future__ import annotations

import json

import pytest

from src.core.plugin_health.gather import build_report
from src.plugins.host import sidecar_registry
from src.plugins.sdk import api_contract
from tests.python.plugin_health.world import make_world

SHIPPED_FEATURE = "share"
CATALOG_ID = "acme/okclock"


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    try:
        yield w
    finally:
        sidecar_registry.install(None)


def test_feature_and_sidecar_rows_carry_api_version(world):
    code = world.install_catalog(CATALOG_ID, enabled=True)
    manifest_path = code / api_contract.MANIFEST_FILE
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc[api_contract.API_VERSION_KEY] = 1
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    world.settle()
    rows = {r.id: r for r in build_report(world.host, world.rt).rows}
    assert rows[SHIPPED_FEATURE].api_version == 1
    assert rows[CATALOG_ID].api_version == 1
    assert rows[CATALOG_ID].as_wire()["api_version"] == 1
