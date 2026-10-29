
import pytest

from src.core.desktop_app import preferences as prefs


@pytest.mark.parametrize("chord", ["Ctrl+Option+Cmd+C", "Cmd+Shift+K", "Ctrl+Option+Space", "Cmd+F5", "Ctrl+F12", "CmdOrCtrl+Shift+J"])
def test_good_chords_pass(chord):
    assert prefs.validate_hotkey(chord) == chord


@pytest.mark.parametrize("chord", [
    "Cmd+C", "Cmd+V", "Cmd+Q", "Cmd+Space", "Ctrl+A", "Option+C", "Shift+A",
    "Cmd+Command+C", "Cmd+CmdOrCtrl+V", "Control+Ctrl+A",
    "Cmd+Shift+Q", "Cmd+Ctrl+Q", "Cmd+Option+Esc", "Command+Alt+Escape", "Cmd+Shift+4", "Cmd+Option+D",
])
def test_system_and_single_modifier_chords_are_refused(chord):
    with pytest.raises(ValueError):
        prefs.validate_hotkey(chord)


def test_off_stays_off():
    assert prefs.validate_hotkey("") == ""
