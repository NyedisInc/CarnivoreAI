import json
import re
from pathlib import Path

import pytest

from src.cplugs.host import ui_doc

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "web/src/lib/cplug-ui/size-parity.fixture.json").read_text(encoding="utf-8"))


def test_server_still_counts_json_dumps_of_the_document() -> None:
    assert "size = len(json.dumps(document, allow_nan=False))" in Path(ui_doc.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(FIXTURE["documents"]))
def test_fixture_size_is_the_servers_count(name: str) -> None:
    document = FIXTURE["documents"][name]
    assert FIXTURE["sizes"][name] == len(json.dumps(document, allow_nan=False))
    ui_doc.validate(document, routes=(), tools=())


def test_server_size_limit_bites_on_escaped_length(monkeypatch: pytest.MonkeyPatch) -> None:
    document = FIXTURE["documents"]["cjk"]
    exact = FIXTURE["sizes"]["cjk"]
    monkeypatch.setattr(ui_doc, "MAX_BYTES", exact)
    ui_doc.validate(document, routes=(), tools=())
    monkeypatch.setattr(ui_doc, "MAX_BYTES", exact - 1)
    with pytest.raises(ui_doc.UiDocError) as raised:
        ui_doc.validate(document, routes=(), tools=())
    assert raised.value.code == "too_large"
    assert not re.search(r"[^\x00-\x7f]", json.dumps(document))
