
from src.core.attention.prompt_suggestion import PromptSuggestions, suggestion_from_line

RULE = "\x1b[38;5;244m" + "─" * 40 + " Cv-UI ─"
SUGGESTED = "\x1b[39m❯\xa0\x1b[2madd it to the widget menu too\x1b[0m"
TYPED = "\x1b[39m❯\xa0add it to the widget menu too\x1b[7m \x1b[27m"
CURSOR_ON_SUGGESTION = "\x1b[39m❯\xa0\x1b[7ma\x1b[27m\x1b[2mdd it\x1b[0m"


def _plain(line: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", line)


def _screen(input_line: str) -> str:
    return "\n".join(["⏺ done.", "", _plain(RULE), _plain(input_line), _plain(RULE), "  ? for shortcuts", ""])


def test_suggestion_read_from_captured_pane_and_empty_when_typed() -> None:
    assert suggestion_from_line(SUGGESTED) == "add it to the widget menu too"
    assert suggestion_from_line(CURSOR_ON_SUGGESTION) == "add it"
    assert suggestion_from_line(TYPED) is None
    assert suggestion_from_line("\x1b[38;2;10;20;30m❯\xa0typed\x1b[0m") is None

    memory = PromptSuggestions()
    rows = {SUGGESTED: [], TYPED: []}

    def reader(line: str):
        def read_row(row: int) -> str:
            rows[line].append(row)
            return line
        return read_row

    assert memory.update("s", idle=True, screen=_screen(SUGGESTED), read_row=reader(SUGGESTED)) == "add it to the widget menu too"
    assert rows[SUGGESTED] == [3]
    assert memory.update("s", idle=True, screen=None, read_row=reader(SUGGESTED)) == "add it to the widget menu too"
    assert rows[SUGGESTED] == [3]
    assert memory.update("s", idle=True, screen=_screen(TYPED), read_row=reader(TYPED)) is None
    memory.update("s", idle=True, screen=_screen(SUGGESTED), read_row=reader(SUGGESTED))
    assert memory.update("s", idle=False, screen=None, read_row=reader(SUGGESTED)) is None
    assert memory.current("s") is None
    empty = _screen("\x1b[39m❯\xa0")
    assert memory.update("s", idle=True, screen=empty, read_row=reader(TYPED)) is None
    assert rows[TYPED] == [3]
