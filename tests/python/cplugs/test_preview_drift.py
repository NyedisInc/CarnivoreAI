
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.cplugs.host import preview_check
from tests.python.cplugs.preview_fixtures import BAD, GOOD

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "hosted" / "catalog" / "api"
TOOLS = ROOT / "hosted" / "catalog_index" / "tools"


def _load(name: str, path: Path, search: Path):
    sys.path.insert(0, str(search))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(search))


@pytest.fixture(scope="module")
def hero():
    return _load("drift_validate_media", API / "validate_media.py", API)


@pytest.fixture(scope="module")
def port():
    import importlib
    sys.path.insert(0, str(TOOLS))
    try:
        return importlib.import_module("index_builder.preview")
    finally:
        sys.path.remove(str(TOOLS))


def test_the_constants_match(hero, port):
    for module in (preview_check, port):
        assert (module.MAX_BYTES, module.MIN_WIDTH, module.MIN_HEIGHT, module.MAX_SIDE, module.MAX_PIXELS, module.RATIO_MIN, module.RATIO_MAX) == (
            hero.MAX_BYTES, hero.MIN_WIDTH, hero.MIN_HEIGHT, hero.MAX_SIDE, hero.MAX_PIXELS, hero.RATIO_MIN, hero.RATIO_MAX)


@pytest.mark.parametrize("label,raw", [(f"good-{k}", v) for k, v in GOOD.items()] + [(f"bad-{k}", v) for k, v in BAD.items()])
def test_the_three_copies_accept_and_refuse_the_same_bytes(hero, port, label, raw):
    try:
        expected = hero.check_hero(raw)
    except hero.UploadRefused:
        expected = None
    try:
        app = preview_check.check_preview(raw)
    except preview_check.PreviewError:
        app = None
    assert app == expected, label
    assert (port.preview_problem(raw) == "") == (expected is not None), label
