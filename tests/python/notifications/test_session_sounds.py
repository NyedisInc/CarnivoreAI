
from __future__ import annotations

import pytest

from src.core.notifications import card_contract, doc_model, styles
from src.core.notifications.settings_doc import styles_store


def _with(doc, tmux_name, type_id, sound):
    return doc_model.set_local(doc, styles_store.session_key(tmux_name, type_id), sound)


def test_session_override_beats_the_global_pick_and_falls_back() -> None:
    doc = doc_model.set_global(doc_model.empty_doc(), doc_model.style_path("session.question"),
                               {"sound": "ping", "urgency": "active"}, "me")
    assert styles.playback_in(doc, "session.question", "api") == "ping"
    doc = _with(doc, "api", "session.question", "echo")
    assert styles.playback_in(doc, "session.question", "api") == "echo"
    assert styles.playback_in(doc, "session.question", "web") == "ping", "another agent keeps the global pick"
    assert styles.playback_in(doc, "session.finished", "api") == styles.effective_style_in(doc, "session.finished").sound
    assert styles_store.session_sounds(doc, "api") == {"session.question": "echo"}
    assert styles_store.session_sounds(doc, "web") == {}


def test_passive_stays_silent_and_bad_input_is_refused() -> None:
    doc = doc_model.set_global(doc_model.empty_doc(), doc_model.style_path("session.question"),
                               {"sound": "ping", "urgency": "passive"}, "me")
    assert styles.playback_in(_with(doc, "api", "session.question", "echo"), "session.question", "api") == "none"
    with pytest.raises(ValueError):
        styles_store.session_key("a/b", "session.question")
    with pytest.raises(ValueError):
        styles_store.session_key("api", "no.such.type")
    assert set(card_contract.EXTRA_SOUNDS) <= set(card_contract.SOUNDS)
