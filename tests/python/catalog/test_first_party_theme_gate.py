
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ruff: noqa: E402
from src.api.catalog_install_support import _stage_now
from src.core.catalog.first_party import is_first_party_item
from src.core.skills.validate import ArchiveRefused
from src.models.catalog import CatalogItem
from tests.helpers.catalog_surface import build_theme, theme_item_for

EFFECTS = b"export default function effects() {}\n"


def _stage(tmp_path: Path, publisher: str, effects):
    pkg = build_theme(tmp_path / publisher, publisher=publisher, name="snes", effects=effects)
    archive = tmp_path / f"{publisher}.tar.gz"
    archive.write_bytes(pkg.tar_bytes)
    raw = theme_item_for(pkg, publisher=publisher, name="snes")
    item = CatalogItem.model_construct(**raw)
    staged_dir = tmp_path / f"staged-{publisher}"
    return item, staged_dir, lambda: _stage_now(archive, staged_dir, item=item, allow_scripts=True)


def test_theme_code_stages_for_both_community_and_first_party_with_code_gate_flagged(tmp_path):
    from src.core.skills.code_gate import staged_plugin_declares_code
    from src.core.skills.kinds import KIND_THEME

    item, _staged_dir, run = _stage(tmp_path, "someone", EFFECTS)
    assert not is_first_party_item(item)
    staged_comm = run()
    assert (staged_comm.path / "effects.js").read_bytes() == EFFECTS
    assert staged_plugin_declares_code(KIND_THEME, staged_comm.path) is True

    item, _staged_dir, run = _stage(tmp_path, "nyedis", EFFECTS)
    assert is_first_party_item(item)
    assert (run().path / "effects.js").read_bytes() == EFFECTS

    _, _, run = _stage(tmp_path, "plain", None)
    staged_plain = run()
    assert (staged_plain.path / "theme.json").is_file()
    assert staged_plugin_declares_code(KIND_THEME, staged_plain.path) is False


def _theme_dir(root: Path, extra: dict) -> Path:
    root.mkdir(parents=True)
    (root / "theme.json").write_text('{"id": "snes", "name": "snes"}', encoding="utf-8")
    for name, data in extra.items():
        (root / name).write_bytes(data)
    return root


@pytest.mark.parametrize("publisher", ["someone", "nyedis"])
@pytest.mark.parametrize("license_name", ["LICENSE", "LICENSE.md"])
def test_metadata_and_scripts_pass_while_symlinks_and_unknown_keys_are_refused(tmp_path, publisher, license_name):
    from src.core.catalog.first_party import refuse_theme_code

    item = CatalogItem.model_construct(**theme_item_for(build_theme(tmp_path / "pkg", publisher=publisher, name="snes"), publisher=publisher, name="snes"))
    ok = _theme_dir(tmp_path / "ok", {license_name: b"MIT", "carnivore.json": b"{}", "effects.js": b"export default () => {};"})
    refuse_theme_code(item, ok)

    bad_key = tmp_path / "bad-key"
    bad_key.mkdir(parents=True)
    (bad_key / "theme.json").write_text('{"id": "snes", "name": "snes", "bogus": 1}', encoding="utf-8")
    with pytest.raises(ArchiveRefused) as refused:
        refuse_theme_code(item, bad_key)
    assert refused.value.code == "scripts_not_supported"

    bad_link = _theme_dir(tmp_path / "bad-link", {})
    (bad_link / "escape.js").symlink_to(tmp_path / "pkg")
    with pytest.raises(ArchiveRefused) as refused:
        refuse_theme_code(item, bad_link)
    assert refused.value.code == "scripts_not_supported"
