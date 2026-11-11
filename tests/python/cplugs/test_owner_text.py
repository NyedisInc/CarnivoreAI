
from __future__ import annotations

import time

import pytest

from src.cplugs.sdk.owner_text import owner_text, sanitize, stored_text
from src.cplugs.sdk.visible_text import TextRefused, clean_json

REFUSED = {"bidi U+202E": "\u202e", "isolate U+2066": "\u2066", "tag U+E0041": "\U000e0041", "stray ESC": "\x1b", "C0 U+001C": "\x1c",
           "U+2028": "\u2028"}
STRIPPED = {"BOM": "\ufeff", "zero width U+200B": "\u200b", "soft hyphen": "\u00ad", "DEL": "\x7f", "C1 U+0085": "\x85"}
COLORED_LOG = "\x1b[1;31mFAIL\x1b[0m test_a\r\n\x1b]8;;https://x.test/a\x07open\x1b]8;;\x1b\\ trace\r\n\x9b32mok\x9b0m\rdone"
CLEAN_LOG = "FAIL test_a\nopen trace\nok\ndone"


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_what_is_never_typed_by_accident_is_refused(name: str) -> None:
    with pytest.raises(TextRefused, match="hidden or control"):
        owner_text(f"ship it{REFUSED[name]} now")


@pytest.mark.parametrize("name", sorted(STRIPPED))
def test_what_a_paste_carries_by_accident_is_removed(name: str) -> None:
    assert owner_text(f"ship{STRIPPED[name]} it") == "ship it"


def test_a_pasted_colored_log_comes_through_clean() -> None:
    assert owner_text(COLORED_LOG) == CLEAN_LOG


def test_owner_text_is_richer_than_visitor_text() -> None:
    log = "\n".join(f"\tline {n}" for n in range(500)) + "\n\n\n\n\n```py\nif x:\n\treturn 1\n```"
    assert owner_text(log) == log
    family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
    assert owner_text(f"done {family} \u2714\ufe0f \ue0b0 caf\u00e9\u00a0x") == f"done {family} \u2714\ufe0f \ue0b0 caf\u00e9 x"


def test_the_visitor_rule_keeps_refusing() -> None:
    submission = pytest.importorskip("src.cplugs.reviewboard.public.submission")
    Malformed, visitor_text = submission.Malformed, submission.clean_text
    for bad in ("a\u200bb", "a\x7fb", "a\r\nb", "\x1b[31mred", "a\x85b"):
        with pytest.raises(Malformed):
            visitor_text(bad, 100)


def test_stored_text_is_cleaned_never_refused() -> None:
    assert stored_text("a\u202eb\U000e0041c\x1bd\u200be\r\nf") == "abcde\nf"


def test_payload_strings_are_cleaned_with_a_named_path_and_a_deep_body_never_overflows() -> None:
    assert clean_json({"k\u00a0": ["x\u200b", {"y": "z\u202fz"}], "n": 1}, owner_text) == {"k ": ["x", {"y": "z z"}], "n": 1}
    top_html = lambda path, value: path == ("html",) and isinstance(value, str)  # noqa: E731
    assert clean_json({"html": "\u202e", "t": "a\u00a0b"}, owner_text, top_html) == {"html": "\u202e", "t": "a b"}
    for nested in ({"html": {"note": "\u202e"}}, {"payload": {"html": "\u202e"}}):
        with pytest.raises(TextRefused):
            clean_json(nested, owner_text, top_html)
    with pytest.raises(TextRefused, match=r"^answers\.0\.note may not contain hidden or control characters$"):
        clean_json({"answers": [{"note": "no\u202e"}]}, owner_text)
    with pytest.raises(TextRefused, match="collide"):
        clean_json({"a b": 1, "a\u00a0b": 2}, owner_text)
    deep: dict = {}
    node = deep
    for _ in range(3000):
        node["a"] = {}
        node = node["a"]
    assert isinstance(clean_json(deep, owner_text), dict)


ADVERSARIAL = {"C1 OSC run": "\x9d" * 200_000, "C1 CSI run": "\x9b" * 200_000, "ESC ] run": "\x1b]" * 100_000, "ESC [ run": "\x1b[" * 100_000,
               "OSC then C1": ("\x9da" * 100_000), "long open OSC": "\x1b]" + "a" * 199_998, "DCS run": "\x90" * 200_000,
               "mixed": "\x9d\x9b\x1b]\x1b[;" * 40_000}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_sanitizing_200k_adversarial_characters_is_linear(name: str) -> None:
    started = time.perf_counter()
    sanitize(ADVERSARIAL[name])
    assert time.perf_counter() - started < 0.5
