
from __future__ import annotations

import pytest

from src.core import theme_script_consent, ui_preferences
from tests.helpers.guard_fold import assert_no_offenders

ACCEPTED = {
    "matrix": "a plain lowercase id",
    "claude": "a bundled theme",
    "Neon Rain": "a space, which is an ordinary folder name",
    "_lead": "a leading underscore, which nothing treats specially",
    "a.b-c_d": "the punctuation that was always allowed",
    "a  b": "two spaces, which round trip fine",
    "ab": "the shortest id with a last character",
    "a": "one character",
    "x" * theme_script_consent.MAX_THEME_ID_LENGTH: "exactly the cap",
}

REFUSED = {
    "x" * (theme_script_consent.MAX_THEME_ID_LENGTH + 1): "one over the cap",
    "über": "non-ascii: unreadable in the config audit record",
    "a​b": "a zero-width space, invisible in two ids",
    "a‮b": "a bidi override, which can spoof a name",
    " lead": "a leading space, invisible and trimmable",
    "trail ": "a trailing space, invisible and trimmable",
    ".hidden": "a leading dot, which the scanner skips anyway",
    ".": "the current directory",
    "..": "the parent directory, the traversal case",
    "-flag": "a leading dash, one step from being argv",
    "a/b": "a path separator",
    "a\\b": "the other path separator",
    "a\x00b": "NUL",
    "a\nb": "an embedded newline",
    "matrix\n": "a TRAILING newline, which '$' used to accept",
    "": "empty",
}


def _why_accepted(theme_id: str) -> str:
    return f"{theme_id!r} ({ACCEPTED[theme_id]})"


def _why_refused(theme_id: str) -> str:
    return f"{theme_id!r} ({REFUSED[theme_id]})"


def _check_a_real_folder_name_can_be_keyed(theme_id: str) -> None:
    assert theme_script_consent.is_keyable_theme_id(theme_id)


def test_a_real_folder_name_can_be_keyed() -> None:
    assert_no_offenders(
        "a real folder name can be keyed",
        ACCEPTED,
        _check_a_real_folder_name_can_be_keyed,
        label=_why_accepted,
    )


def _check_an_unsafe_name_is_refused(theme_id: str) -> None:
    assert not theme_script_consent.is_keyable_theme_id(theme_id)


def test_an_unsafe_name_is_refused() -> None:
    assert_no_offenders(
        "an unsafe name is refused",
        REFUSED,
        _check_an_unsafe_name_is_refused,
        label=_why_refused,
    )


def test_a_non_string_is_refused_rather_than_crashing() -> None:
    for value in (None, 123, [], {}, object()):
        assert not theme_script_consent.is_keyable_theme_id(value)


def _check_an_accepted_id_can_actually_record_a_refusal(theme_id: str) -> None:
    out = theme_script_consent.validate_consent_map(
        {theme_id: {"decision": "never"}}
    )
    assert out == {theme_id: {"decision": "never"}}


def test_an_accepted_id_can_actually_record_a_refusal() -> None:
    assert_no_offenders(
        "an accepted id can actually record a refusal",
        ACCEPTED,
        _check_an_accepted_id_can_actually_record_a_refusal,
        label=_why_accepted,
    )


def _check_a_refused_id_is_still_refused_by_the_map(theme_id: str) -> None:
    with pytest.raises(ValueError):
        theme_script_consent.validate_consent_map(
            {theme_id: {"decision": "never"}}
        )


def test_a_refused_id_is_still_refused_by_the_map() -> None:
    assert_no_offenders(
        "a refused id is still refused by the map",
        REFUSED,
        _check_a_refused_id_is_still_refused_by_the_map,
        label=_why_refused,
    )


def test_the_selected_theme_uses_the_same_rule_as_the_consent_key() -> None:
    assert ui_preferences.THEME_ID_RE is theme_script_consent.THEME_ID_RE


def _check_an_accepted_id_can_also_be_the_selected_theme(theme_id: str) -> None:
    values = ui_preferences.UiPreferenceValues(theme=theme_id)
    assert values.theme == theme_id


def test_an_accepted_id_can_also_be_the_selected_theme() -> None:
    assert_no_offenders(
        "an accepted id can also be the selected theme",
        ACCEPTED,
        _check_an_accepted_id_can_also_be_the_selected_theme,
        label=_why_accepted,
    )
