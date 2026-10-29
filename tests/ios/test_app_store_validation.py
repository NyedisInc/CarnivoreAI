
from __future__ import annotations

import json
import plistlib
import re
import struct
from pathlib import Path

IOS = Path(__file__).resolve().parents[2] / "ios"
APPICON = IOS / "Carnivore" / "Assets.xcassets" / "AppIcon.appiconset"


def _target_blocks() -> dict[str, str]:
    text = (IOS / "project.yml").read_text()
    section = text.split("\ntargets:\n", 1)[1].split("\nschemes:", 1)[0]
    parts = re.split(r"(?m)^  (\w+):\n", section)
    return dict(zip(parts[1::2], parts[2::2]))


def test_every_target_pins_iphone_only() -> None:
    blocks = _target_blocks()
    assert {"Carnivore", "CarnivoreNotify"} <= set(blocks)
    for name, body in blocks.items():
        assert re.search(r'(?m)^\s+TARGETED_DEVICE_FAMILY: "1"\s*$', body), name


def test_app_icon_is_an_opaque_1024_png() -> None:
    images = json.loads((APPICON / "Contents.json").read_text())["images"]
    assert len(images) == 1 and images[0]["size"] == "1024x1024"
    data = (APPICON / images[0]["filename"]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    assert (width, height) == (1024, 1024)
    assert color_type in (0, 2, 3)
    assert b"tRNS" not in data
    assert "ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon" in _target_blocks()["Carnivore"]


def test_camera_purpose_string_present_when_camera_used() -> None:
    uses_camera = any("AVCaptureDevice" in p.read_text() for p in (IOS / "Carnivore").glob("*.swift"))
    assert uses_camera
    info = plistlib.loads((IOS / "Carnivore" / "Info.plist").read_bytes())
    assert info.get("NSCameraUsageDescription")
