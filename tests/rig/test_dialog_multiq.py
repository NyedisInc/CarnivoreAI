
from __future__ import annotations

import time

import pytest

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_dialog_answer import call, session_id, tool_results, wait_dialog, wait_for

Q3 = {"questions": [
    {"question": "Best hacker movie?", "header": "Movie", "multiSelect": False,
     "options": [{"label": "Hackers", "description": "1995. Hack the planet."},
                 {"label": "The Matrix", "description": "1999. There is no spoon."},
                 {"label": "Sneakers", "description": "1992. Too many secrets."},
                 {"label": "WarGames", "description": "1983. Shall we play a game?"}]},
    {"question": "Which bands?", "header": "Bands", "multiSelect": True,
     "options": [{"label": "Pantera", "description": "1990. Cowboys from Hell."},
                 {"label": "Slayer", "description": "1986. Reign in Blood."},
                 {"label": "Sepultura", "description": "1996. Roots."}]},
    {"question": "Fuel?", "header": "Fuel", "multiSelect": False,
     "options": [{"label": "Coffee", "description": "black"}, {"label": "Pizza", "description": "NYC slice"}]}]}


def wait_question(slot, sid: str, text: str, timeout: float = 30.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        dialog = wait_dialog(slot, sid, timeout)
        if dialog["question"] == text:
            return dialog
        time.sleep(1.0)
    raise AssertionError(f"never saw the question {text!r}")


def test_three_question_ask_is_counted_and_answered(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    with ScriptedModel([Step("RIG:q3", "AskUserQuestion", Q3)]) as model:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        name = rig_slot.create_session("rigq", "rigclaude", cwork)
        sid = session_id(rig_slot, name)
        path = f"/api/v1/sessions/{sid}/dialog/answer"
        rig_slot.wait_for(name, "❯")
        rig_slot.type_line(name, "RIG:q3 go")
        rig_slot.wait_for(name, "Best hacker movie?")

        first = wait_question(rig_slot, sid, "Best hacker movie?")
        assert first["options"] == ["Hackers", "The Matrix", "Sneakers", "WarGames"]
        assert (first["question_index"], first["question_total"]) == (1, 3)
        assert first["rows"][0]["description"].startswith("1995. Hack the planet")

        for text, choice in (("Best hacker movie?", {"option": "The Matrix"}),
                             ("Which bands?", {"options": ["Pantera", "Slayer"]}),
                             ("Fuel?", {"option": "Pizza"})):
            dialog = wait_question(rig_slot, sid, text)
            status, body = call(rig_slot, "POST", path, {"fingerprint": dialog["fingerprint"], "choice": choice})
            assert status == 200, (text, body, "\n".join(l for l in rig_slot.capture(name).splitlines() if l.strip()))

        wait_for(lambda: all(w in tool_results(model) for w in ("The Matrix", "Pantera", "Slayer", "Pizza")),
                 "the model never saw all three answers " + rig_slot.capture(name), 30)
