
from __future__ import annotations

import pytest

from src.core.message_model_secrets import (
    DETECTOR_ANTHROPIC_API_KEY,
    DETECTOR_AWS_ACCESS_KEY_ID,
    DETECTOR_AWS_SECRET_ACCESS_KEY,
    DETECTOR_CLOUDFLARE_API_TOKEN,
    DETECTOR_GITHUB_TOKEN,
    DETECTOR_GOOGLE_API_KEY,
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_OP_SERVICE_ACCOUNT,
    DETECTOR_OPENAI_API_KEY,
    DETECTOR_SLACK_TOKEN,
    scan_text,
)
from tests.synthetic_credentials import (
    anthropic_key,
    aws_key_id,
    github_token,
    openai_key,
    synthetic_body,
)
from tests.test_stream_redactor_bypass import _redact

BOUNDED = {
    DETECTOR_OP_SERVICE_ACCOUNT: lambda: "op" + "s_" + synthetic_body(48),
    DETECTOR_GITHUB_TOKEN: github_token,
    "github_fine_grained": lambda: "github" + "_pat_" + synthetic_body(82),
    DETECTOR_AWS_ACCESS_KEY_ID: aws_key_id,
    DETECTOR_GOOGLE_API_KEY: lambda: "AI" + "za" + synthetic_body(35),
    DETECTOR_SLACK_TOKEN: lambda: "xo" + "xb-" + synthetic_body(24),
    DETECTOR_CLOUDFLARE_API_TOKEN: lambda: "cf" + "_api_token=" + synthetic_body(40),
    DETECTOR_ANTHROPIC_API_KEY: anthropic_key,
    DETECTOR_OPENAI_API_KEY: openai_key,
}


def _detector(name: str) -> str:
    return DETECTOR_GITHUB_TOKEN if name == "github_fine_grained" else name


@pytest.mark.parametrize("name", sorted(BOUNDED))
@pytest.mark.parametrize("escape", ["\\n", "\\r", "\\t"])
def test_a_key_after_a_literal_escape_is_found(name: str, escape: str) -> None:
    value = BOUNDED[name]()
    assert _detector(name) in [f.detector for f in scan_text(value)]
    text = '{"text":"here it is:' + escape + value + '"}'
    assert _detector(name) in [f.detector for f in scan_text(text)]


@pytest.mark.parametrize("name", sorted(BOUNDED))
def test_a_real_letter_in_front_is_still_not_a_boundary(name: str) -> None:
    text = "x" + BOUNDED[name]()
    assert _detector(name) not in [f.detector for f in scan_text(text)]


def test_the_spectator_scrubber_stars_a_key_after_an_escape() -> None:
    value = anthropic_key()
    out = _redact('{"text":"here it is:\\n' + value + '"}\r\n')
    assert value not in out and "*" * len(value) in out




def test_the_guards_drop_it_by_default_and_redaction_keeps_it() -> None:
    value = "gh" + "p_" + "".join(c for c in synthetic_body(80, "GHJKLQVWZgjkqvwz") if c.isalpha())[:36]
    assert len(value) == 40 and not any(c.isdigit() for c in value)
    assert scan_text(value) == []
    kept = scan_text(value, trust_vendor_marker=True)
    assert [f.detector for f in kept] == [DETECTOR_GITHUB_TOKEN]
    assert value not in _redact("found " + value + "\r\n")


def test_redaction_keeps_a_vendor_key_carrying_a_placeholder_word() -> None:
    value = anthropic_key()[:-12] + "test1234abAA"
    assert scan_text(value) == []
    assert [f.detector for f in scan_text(value, trust_vendor_marker=True)] == [
        DETECTOR_ANTHROPIC_API_KEY]


def test_the_generic_assignment_detector_keeps_its_guards_in_redaction() -> None:
    text = "api_key=your_api_key_goes_here_please"
    assert scan_text(text, trust_vendor_marker=True) == []
    real = "api_key=" + synthetic_body(32)
    assert [f.detector for f in scan_text(real, trust_vendor_marker=True)] == [
        DETECTOR_HIGH_ENTROPY_ASSIGNMENT]




@pytest.mark.parametrize(
    "spelling",
    ["\\u001b[32m", "\\u001b[1;32m", "\\x1b[32m", "\\u0027", "\\u003d", "\\u000a"],
)
@pytest.mark.parametrize("name", sorted(BOUNDED))
def test_redaction_finds_a_key_after_any_escape_spelling(name: str, spelling: str) -> None:
    value = BOUNDED[name]()
    text = '{"c":"' + spelling + value + '"}'
    assert _detector(name) in [f.detector for f in scan_text(text, trust_vendor_marker=True)]
    out = _redact(text + "\r\n")
    assert value not in out


@pytest.mark.parametrize("name", sorted(BOUNDED))
def test_redaction_finds_a_key_glued_to_prose_on_both_sides(name: str) -> None:
    value = BOUNDED[name]()
    text = "isthe" + value + "thenrestart"
    assert _detector(name) in [f.detector for f in scan_text(text, trust_vendor_marker=True)]


def test_a_json_escaped_quote_around_a_contextual_name_is_read() -> None:
    value = synthetic_body(40, "GHJKLQVWZgjkqvwz56789+/")
    text = '{"c":"aws_secret_access_key\\": \\"' + value + '\\""}'
    found = [f.detector for f in scan_text(text, trust_vendor_marker=True)]
    assert DETECTOR_AWS_SECRET_ACCESS_KEY in found
    assert scan_text(text) == [] or DETECTOR_AWS_SECRET_ACCESS_KEY not in [
        f.detector for f in scan_text(text)]
