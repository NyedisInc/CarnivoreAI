
from __future__ import annotations

import re
from pathlib import Path

from src.plugins.reviewboard.public import announce

CATALOG = Path(__file__).resolve().parents[5] / "web" / "src" / "plugins" / "reviewboard" / "catalog.en.js"
KEY = re.compile(r"^\s*'(cplug\.[a-z0-9_.]+)':", re.M)


def catalog_keys() -> set:
    keys = set(KEY.findall(CATALOG.read_text(encoding="utf-8")))
    assert len(keys) > 50, "the catalog was not read"
    return keys


def test_the_alert_title_and_detail_keys_resolve_in_the_catalog() -> None:
    keys = catalog_keys()
    assert announce.ALERT_TITLE_KEY in keys and announce.ALERT_DETAIL_KEY in keys


def test_no_server_constant_names_the_retired_publicboard_catalog() -> None:
    public = Path(announce.__file__).parent
    stale = sorted(p.name for p in public.glob("*.py") if re.search(r"cplug\.publicboard\.", p.read_text(encoding="utf-8")))
    assert stale == [], "these name keys of the retired plugin's catalog, which no longer exists"


def test_the_lookup_can_fail() -> None:
    assert "cplug.publicboard.alert.visitor_posted" not in catalog_keys()
