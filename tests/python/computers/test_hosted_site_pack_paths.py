import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[3] / "hosted" / "site"
OLD_PATH = re.compile(r'find "pack"|find pack,')


def test_site_routes_pack_through_the_menu() -> None:
    files = (SITE / "link" / "index.html", SITE / "install.sh")
    assert [p.name for p in files if OLD_PATH.search(p.read_text(encoding="utf-8"))] == []
    assert '"menu", then "pack"' in (SITE / "link" / "index.html").read_text(encoding="utf-8") or 'menu, then "pack"' in (SITE / "link" / "index.html").read_text(encoding="utf-8")
    assert "open the menu, then pack" in (SITE / "install.sh").read_text(encoding="utf-8")
