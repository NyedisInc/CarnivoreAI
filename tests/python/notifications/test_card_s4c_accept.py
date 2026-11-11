import json
from pathlib import Path

from src.core.notifications.cards.build import _body

REPO = Path(__file__).resolve().parents[3]


def test_link_body_tail_is_a_middle_dot() -> None:
    assert _body({"text": "preview is ready", "host": "carnivore.ai", "url": "https://carnivore.ai/preview"}, "fixed") == "preview is ready · carnivore.ai"
    fixture = json.loads((REPO / "tests/fixtures/notify_cards/link.json").read_text())
    assert "preview is ready · carnivore.ai" in json.dumps(fixture, ensure_ascii=False)
    assert "ready . carnivore" not in json.dumps(fixture)


def test_title_from_agent_label_is_gone() -> None:
    for rel in ("client/js/i18n/catalog.en.js", "src/core/notifications/card_contract.py", "ios/Shared/Generated/NotifyContract.swift", "web/src/lib/notify-card/contract.gen.ts"):
        assert "title_from_agent" not in (REPO / rel).read_text(), rel
