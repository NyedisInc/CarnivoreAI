
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_al_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_al_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ruff: noqa: E402
from src.api.catalog_install_support import _stage_now
from src.core.skills.validate import ArchiveRefused
from src.models.catalog import CatalogItem
from src.models.catalog_names import FIRST_PARTY_THEME_PUBLISHER
from tests.helpers.catalog_surface import build_theme, theme_item_for

BASE = b"export function createEffect() {}\n"


def _stage(tmp_path: Path, publisher: str, effects, files=None):
    pkg = build_theme(tmp_path / publisher, publisher=publisher, name="snes", effects=effects, files=files)
    archive = tmp_path / f"{publisher}.tar.gz"
    archive.write_bytes(pkg.tar_bytes)
    item = CatalogItem.model_construct(**theme_item_for(pkg, publisher=publisher, name="snes"))
    return _stage_now(archive, tmp_path / f"staged-{publisher}", item=item, allow_scripts=True)


def test_community_xhtml_refused(tmp_path):
    with pytest.raises(ArchiveRefused) as refused:
        _stage(tmp_path, "someone", None, {"login.xhtml": b"<html/>"})
    assert refused.value.code == "scripts_not_supported"
    assert not (tmp_path / "staged-someone").exists()


def test_first_party_import_must_stay_in_folder(tmp_path):
    bad = b"import { createEffect } from '../_shared/effects-base.js';\nexport default () => {};\n"
    with pytest.raises(ArchiveRefused) as refused:
        _stage(tmp_path, FIRST_PARTY_THEME_PUBLISHER, bad, {"effects-base.js": BASE})
    assert refused.value.code == "scripts_not_supported"
    assert not (tmp_path / f"staged-{FIRST_PARTY_THEME_PUBLISHER}").exists()


def test_first_party_vendored_base_stages(tmp_path):
    good = b"import { createEffect } from './effects-base.js';\nexport default () => {};\n"
    staged = _stage(tmp_path, FIRST_PARTY_THEME_PUBLISHER, good, {"effects-base.js": BASE})
    assert (staged.path / "effects.js").is_file() and (staged.path / "effects-base.js").is_file()
