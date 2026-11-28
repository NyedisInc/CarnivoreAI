from __future__ import annotations

import pytest

from src.plugins.host.plugin_manifest import from_manifest_v2
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2

BASE = {
    "schema": 2,
    "id": "pillpanic",
    "name": "Pill Panic",
    "description": "d",
    "version": "1.0.0",
    "kind": "plugin",
    "author": "me",
    "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
}


def views(fits=None, omit=False):
    view = {"name": "game", "surfaces": ["panel"], "files": ["index.html"]}
    if not omit:
        view["fits"] = fits
    v2 = parse_manifest_v2({**BASE, "ui": {"views": [view]}})
    return from_manifest_v2(v2, "d").views[0]


def test_a_clean_fits_is_kept_ordered_and_an_absent_one_is_the_default():
    got = views({"sizes": ["large", "small"], "min": {"w": 1, "h": 1}, "anySize": True})["fits"]
    assert got == {"sizes": ["small", "large"], "min": {"w": 1, "h": 1}, "anySize": True}
    assert views({"sizes": ["medium"]})["fits"] == {"sizes": ["medium"], "min": {"w": 4, "h": 4}, "anySize": False}
    assert views(omit=True)["fits"] == {"sizes": ["medium", "large", "full"], "min": {"w": 3, "h": 3}, "anySize": True}


@pytest.mark.parametrize("bad", [
    {"sizes": ["huge"]}, {"sizes": []}, {"sizes": ["medium", "medium"]}, {"sizes": "medium"}, {}, {"sizes": [{}]},
    {"sizes": ["medium"], "extra": 1}, {"sizes": ["medium"], "anySize": "yes"},
    {"sizes": ["medium"], "min": {"w": 0, "h": 1}}, {"sizes": ["medium"], "min": {"w": 13, "h": 1}}, {"sizes": ["medium"], "min": {"w": 1.5, "h": 1}},
    {"sizes": ["medium"], "min": {"w": True, "h": 1}}, {"sizes": ["medium"], "min": {"w": 1}}, {"sizes": ["medium"], "min": {"w": 5, "h": 1}},
    {"sizes": ["small", "large"], "min": {"w": 1, "h": 2}},
])
def test_a_bad_fits_refuses_the_manifest(bad):
    with pytest.raises(ManifestV2Error):
        views(bad)
