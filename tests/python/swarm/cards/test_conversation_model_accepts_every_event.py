import pytest

from src.core.swarm.stream_sources import EVENTS
from src.models.swarm import SwarmConversationPage


@pytest.mark.parametrize("event", EVENTS)
def test_conversation_page_accepts_event(event: str) -> None:
    entry = {"kind": "event", "id": f"ev:{event}:1", "at": 1.0, "event": event, "ref": "card:1", "text": "x"}
    assert SwarmConversationPage.model_validate({"entries": [entry], "cursor": None}).entries
