from __future__ import annotations

import struct
from pathlib import Path

from scripts.widgets import capture_one, catalog_meta, common, defects, gate


def test_page_height_is_desktop_above_500_and_phone_at_or_below() -> None:
    assert common.page_height(501) == 1100 and common.page_height(390) == 844 and common.page_height(500) == 844


def test_viewport_for_box_adds_the_stage_margin_and_page_uses_the_height() -> None:
    assert common.viewport_for({"w": 100, "h": 50, "viewport": 390}, "box") == {"width": 132, "height": 82}
    assert common.viewport_for({"viewport": 800}, "page") == {"width": 800, "height": 1100}


def test_key_slug_and_key_matches() -> None:
    assert common.key_slug("core.analytics:vitals") == "core.analytics--vitals"
    assert common.key_matches("a:b", []) and common.key_matches("a:b", ["a:"]) and not common.key_matches("a:b", ["a"])


def test_png_dimensions_reads_ihdr_and_rejects_non_png() -> None:
    header = common.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 7, 9)
    assert common.png_dimensions(header) == (7, 9)
    assert common.png_dimensions(b"nope") is None and common.png_dimensions(common.PNG_SIGNATURE) is None


def test_every_widget_script_uses_the_shared_helpers_not_private_copies() -> None:
    assert capture_one.png_dimensions is common.png_dimensions
    assert gate.source_revision is common.source_revision
    assert catalog_meta.source_revision is common.source_revision
    assert defects.viewport_for is common.viewport_for
    assert not hasattr(capture_one, "source_revision") or capture_one.source_revision is common.source_revision
    assert not hasattr(catalog_meta, "_git") and not hasattr(defects, "wanted")
    assert gate.GLANCE_SIZE == "glance" and gate.POPOUT_HOST == "popout"


def test_source_revision_names_a_sha_for_a_repo() -> None:
    rev = common.source_revision(Path(__file__).resolve().parents[3])
    assert len(rev["sha"]) == 40 and isinstance(rev["dirty"], bool)
