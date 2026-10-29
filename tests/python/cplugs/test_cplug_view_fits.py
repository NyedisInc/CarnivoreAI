from __future__ import annotations

import pytest

from src.cplugs.host.sidecar_manifest import SidecarManifestError, parse_sidecar_manifest

BASE = {"schema": 1, "id": "bubblepop", "name": "Bubble Pop", "description": "d", "version": "1.0.0", "entry": "main.py", "tools": [],
        "permissions": {"app": []}, "default_enabled": False, "routes": []}


def views(fits=None, omit=False):
    view = {"name": "game", "surfaces": ["panel"], "files": ["index.html"]}
    if not omit:
        view["fits"] = fits
    return parse_sidecar_manifest({**BASE, "views": [view]}, "bubblepop", "d").views[0]


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
    with pytest.raises(SidecarManifestError):
        views(bad)
