import re
from pathlib import Path

from src.cplugs.host import sidecar_manifest

ROOT = Path(__file__).resolve().parents[3]
NAMED_SIZES_TS = (ROOT / "web/src/opscenter/widgets/named-sizes.ts").read_text(encoding="utf-8")
PANEL_VIEWS_TS = (ROOT / "web/src/lib/cplug-ui/panel-views.svelte.ts").read_text(encoding="utf-8")
CONSTANTS_TS = (ROOT / "web/src/opscenter/cells/plugin-view/constants.ts").read_text(encoding="utf-8")


def _ts_units() -> dict[str, tuple[int, int]]:
    body = NAMED_SIZES_TS.split("export const NAMED_SIZE_UNITS", 1)[1].split("});", 1)[0]
    found = re.findall(r"^\s*(\w+): Object\.freeze\(\{ w: (\d+), h: (\d+) \}\)", body, re.MULTILINE)
    return {name: (int(w), int(h)) for name, w, h in found}


def _ts_names() -> list[str]:
    raw = re.search(r"GRID_SIZE_NAMES = \[([^\]]*)\]", NAMED_SIZES_TS)
    assert raw, "GRID_SIZE_NAMES not found in named-sizes.ts"
    return re.findall(r"'(\w+)'", raw.group(1))


def test_named_units_equal_the_apps() -> None:
    ts = _ts_units()
    assert ts, "no sizes parsed from named-sizes.ts (the parser is blind)"
    assert dict(sidecar_manifest._NAMED_UNITS) == ts


def test_size_names_and_their_order_equal_the_apps() -> None:
    assert list(sidecar_manifest._NAMED_UNITS) == _ts_names()


def test_default_contract_equals_the_apps() -> None:
    sizes = re.search(r"DEFAULT_FITS: PanelFits = \{ sizes: \[([^\]]*)\]", PANEL_VIEWS_TS)
    floor = re.search(r"DEFAULT_PANEL_MIN = \{ w: (\d+), h: (\d+) \}", CONSTANTS_TS)
    assert sizes and floor, "the app's default contract was not found"
    server = sidecar_manifest.DEFAULT_VIEW_FITS
    assert re.findall(r"'(\w+)'", sizes.group(1)) == server["sizes"]
    assert {"w": int(floor.group(1)), "h": int(floor.group(2))} == server["min"]
    assert "anySize: true" in PANEL_VIEWS_TS.split("DEFAULT_FITS: PanelFits", 1)[1].split("\n", 1)[0] and server["anySize"] is True


def test_the_server_still_accepts_small_and_wide_so_a_field_view_that_declares_them_loads() -> None:
    fits = sidecar_manifest._fits({"sizes": ["small", "wide"]}, "field view")
    assert fits["sizes"] == ["small", "wide"]
