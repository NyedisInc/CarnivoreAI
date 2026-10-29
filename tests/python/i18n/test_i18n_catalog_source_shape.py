import re
from collections import Counter
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
ENTRY_LINE = re.compile(
    r"""^\s*'(?P<key>[a-z0-9_.]+)':\s*(?:'(?P<single>(?:[^'\\]|\\.)*)'|"(?P<double>(?:[^"\\]|\\.)*)"),\s*$"""
)
ENTRY_START = re.compile(r"""^\s*'(?P<key>[a-z0-9_.]+)':\s*['"]""")

KNOWN_REPEATED_KEYS = {
    "sessions.page.sort.label",
}
KNOWN_MULTI_LINE_KEYS = {
    "sidebar.project.remove.detail_empty",
    "sidebar.project.remove_partial",
}


def _lines() -> list[str]:
    return CATALOG.read_text(encoding="utf-8").split("\n")


def test_positive_control_the_scan_sees_entries() -> None:
    keys = [m.group("key") for line in _lines() if (m := ENTRY_START.match(line))]
    assert len(keys) > 1000, "the scan found almost nothing, so the checks below would be vacuous"


def test_no_key_is_repeated_outside_the_known_list() -> None:
    counts = Counter(m.group("key") for line in _lines() if (m := ENTRY_START.match(line) or re.match(r"^\s*'(?P<key>[a-z0-9_.]+)':", line)))
    repeated = {key for key, n in counts.items() if n > 1}
    assert repeated <= KNOWN_REPEATED_KEYS, f"new repeated keys (the later one silently wins): {sorted(repeated - KNOWN_REPEATED_KEYS)}"
    assert KNOWN_REPEATED_KEYS <= repeated, f"fixed, remove from KNOWN_REPEATED_KEYS: {sorted(KNOWN_REPEATED_KEYS - repeated)}"


def test_every_string_entry_sits_on_one_line_the_server_reader_can_parse() -> None:
    unparseable = {
        m.group("key") for line in _lines() if (m := ENTRY_START.match(line)) and not ENTRY_LINE.match(line)
    }
    assert unparseable <= KNOWN_MULTI_LINE_KEYS, f"entries the one-line reader cannot parse: {sorted(unparseable - KNOWN_MULTI_LINE_KEYS)}"
    assert KNOWN_MULTI_LINE_KEYS <= unparseable, f"fixed, remove from KNOWN_MULTI_LINE_KEYS: {sorted(KNOWN_MULTI_LINE_KEYS - unparseable)}"
