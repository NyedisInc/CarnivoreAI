
from __future__ import annotations

from typing import Any, Dict

import pytest

from scripts.gate import field_installs as fi
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2


def _v2(**extra: Any) -> Dict[str, Any]:
    return {
        "schema": 2,
        "id": "clock",
        "name": "Clock",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Tells time.",
        "author": "me",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        **extra,
    }


@pytest.mark.parametrize("version", ["1.16.2", "1.16.6", "1.17.0", "2.0.0"])
def test_valid_min_app_version_is_preserved(version: str) -> None:
    assert parse_manifest_v2(_v2(min_app_version=version)).min_app_version == version


def test_absent_min_app_version_defaults_to_empty() -> None:
    assert parse_manifest_v2(_v2()).min_app_version == ""


@pytest.mark.parametrize("bad", ["", "1.16", ">=1.16.6", "latest", "1.16.6-beta", 116, True])
def test_invalid_min_app_version_is_refused(bad: Any) -> None:
    with pytest.raises(ManifestV2Error, match="min_app_version"):
        parse_manifest_v2(_v2(min_app_version=bad))


def test_floor_check_enforces_min_app_version_on_field_apps() -> None:
    refusal, _note = fi.floor_check("1.16.6", fi.FIELD_FLOOR, upcoming=False)
    assert "1.16.6" in refusal
    assert fi.floor_check("1.16.6", "1.16.6", upcoming=False) == ("", "")
    assert fi.floor_check("1.16.6", "1.16.7", upcoming=False) == ("", "")
