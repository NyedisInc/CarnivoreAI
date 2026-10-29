
from __future__ import annotations

import pytest

from src.core import theme_script_consent as consent
from src.core import theme_script_digest as digest
from src.core import ui_preferences

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _decide(**overrides):
    spec = {
        "declares_script": True,
        "source": consent.SOURCE_USER,
        "served_digest": DIGEST_A,
        "record": None,
        "record_readable": True,
    }
    spec.update(overrides)
    return consent.decide(**spec)




def test_a_theme_with_no_script_is_not_a_consent_question():
    verdict = _decide(declares_script=False)
    assert verdict.outcome == consent.SKIP_NO_SCRIPT
    assert verdict.may_run is False


def test_a_recorded_refusal_refuses():
    verdict = _decide(record={"decision": "never"})
    assert verdict.outcome == consent.SKIP_DENIED
    assert verdict.may_run is False


def test_a_refusal_outranks_the_bundled_bypass():
    allowed = _decide(source=consent.SOURCE_BUILTIN, record=None)
    assert allowed.may_run is True and allowed.rung == consent.RUNG_BUILTIN

    refused = _decide(source=consent.SOURCE_BUILTIN, record={"decision": "never"})
    assert refused.outcome == consent.SKIP_DENIED
    assert refused.may_run is False


def test_first_party_user_theme_runs_but_never_over_a_refusal():
    ran = _decide(source=consent.SOURCE_USER, record=None, script_trust="first_party")
    assert ran.may_run is True and ran.rung == consent.RUNG_FIRST_PARTY

    denied = _decide(source=consent.SOURCE_USER, record={"decision": "never"},
                     script_trust="first_party")
    assert denied.outcome == consent.SKIP_DENIED

    assert _decide(source=consent.SOURCE_USER, record=None).outcome == consent.PROMPT
    assert _decide(source=consent.SOURCE_USER, record=None,
                   script_trust="other").outcome == consent.PROMPT


def test_a_refusal_outranks_an_unreadable_record():
    verdict = _decide(record={"decision": "never"}, record_readable=False)
    assert verdict.rung == consent.RUNG_DENIED


def test_an_unreadable_record_refuses_a_cached_grant():
    verdict = _decide(
        record={"decision": "always", "digest": DIGEST_A}, record_readable=False
    )
    assert verdict.outcome == consent.SKIP_UNVERIFIABLE
    assert verdict.rung == consent.RUNG_RECORD_UNREADABLE
    assert verdict.may_run is False


def test_a_user_theme_whose_bytes_could_not_be_named_never_runs():
    verdict = _decide(
        served_digest=None, record={"decision": "always", "digest": DIGEST_A}
    )
    assert verdict.outcome == consent.SKIP_UNVERIFIABLE
    assert verdict.rung == consent.RUNG_DIGEST_UNAVAILABLE


def test_a_malformed_digest_is_not_a_digest():
    verdict = _decide(served_digest="not-a-sha256")
    assert verdict.outcome == consent.SKIP_UNVERIFIABLE


def test_a_grant_covers_the_bytes_it_named_and_no_others():
    same = _decide(record={"decision": "always", "digest": DIGEST_A})
    assert same.may_run is True and same.rung == consent.RUNG_GRANTED

    edited = _decide(record={"decision": "always", "digest": DIGEST_B})
    assert edited.outcome == consent.PROMPT_CHANGED
    assert edited.may_run is False


def test_nothing_on_record_asks_rather_than_running():
    verdict = _decide(record=None)
    assert verdict.outcome == consent.PROMPT
    assert verdict.may_run is False


def test_an_unrecognised_source_is_treated_as_a_user_theme():
    verdict = _decide(source="somewhere-else", record=None)
    assert verdict.outcome == consent.PROMPT


def test_exactly_one_outcome_permits_execution():
    every = {
        consent.RUN,
        consent.SKIP_NO_SCRIPT,
        consent.SKIP_DENIED,
        consent.SKIP_UNVERIFIABLE,
        consent.PROMPT,
        consent.PROMPT_CHANGED,
    }
    assert consent.RUNNING_OUTCOMES == {consent.RUN}
    assert len(every) == 6




def test_allow_once_is_never_a_stored_record():
    assert consent.record_for("once", DIGEST_A) is None


def test_a_grant_with_no_digest_cannot_be_built():
    assert consent.record_for("always", None) is None
    assert consent.record_for("always", "short") is None
    assert consent.record_for("always", DIGEST_A) == {
        "decision": "always",
        "digest": DIGEST_A,
    }


def test_a_refusal_carries_no_digest():
    assert consent.record_for("never", DIGEST_A) == {"decision": "never"}


def test_the_preference_block_refuses_an_unbounded_grant():
    with pytest.raises(ValueError) as exc:
        ui_preferences.validate_changes(
            {"theme_script_consent": {"matrix": {"decision": "always"}}}
        )
    assert "digest" in str(exc.value)


def test_the_preference_block_refuses_the_word_once():
    with pytest.raises(ValueError) as exc:
        ui_preferences.validate_changes(
            {"theme_script_consent": {"matrix": {"decision": "once"}}}
        )
    assert "once" in str(exc.value)


def test_the_preference_block_accepts_a_bounded_grant_and_a_refusal():
    out = ui_preferences.validate_changes(
        {
            "theme_script_consent": {
                "matrix": {"decision": "always", "digest": DIGEST_A},
                "snes": {"decision": "never"},
            }
        }
    )
    assert out["theme_script_consent"] == {
        "matrix": {"decision": "always", "digest": DIGEST_A},
        "snes": {"decision": "never"},
    }


def test_a_refusal_does_not_keep_a_digest_it_was_sent():
    out = consent.validate_consent_map(
        {"matrix": {"decision": "never", "digest": DIGEST_A}}
    )
    assert out["matrix"] == {"decision": "never"}


def test_a_consent_key_must_be_a_theme_id():
    with pytest.raises(ValueError):
        consent.validate_consent_map({"../etc/passwd": {"decision": "never"}})


def test_the_map_is_bounded():
    too_many = {
        f"t{i}": {"decision": "never"}
        for i in range(consent.MAX_CONSENT_ENTRIES + 1)
    }
    with pytest.raises(ValueError):
        consent.validate_consent_map(too_many)




def test_only_a_move_into_a_refusal_is_a_revocation():
    assert consent.revocations_between({}, {"a": {"decision": "never"}}) == ("a",)
    assert (
        consent.revocations_between(
            {"a": {"decision": "never"}}, {"a": {"decision": "never"}}
        )
        == ()
    )
    assert (
        consent.revocations_between(
            {"a": {"decision": "always", "digest": DIGEST_A}}, {}
        )
        == ()
    )




def test_the_digest_is_of_the_whole_folder_not_the_entry_point(tmp_path):
    import hashlib

    from src.core.skills.digest import digest_directory

    theme = tmp_path / "matrix"
    theme.mkdir()
    body = b"export function init() {}\n"
    (theme / "effects.js").write_bytes(body)
    (theme / "theme.json").write_text('{"id": "matrix", "effects": "effects.js"}')

    taken = digest.digest_effects(theme, "effects.js")
    assert taken == digest_directory(theme)[0]
    assert taken != hashlib.sha256(body).hexdigest(), (
        "the per-file scheme is the bypass this replaced"
    )


def test_a_changed_sibling_moves_the_digest_though_the_entry_point_did_not(
    tmp_path,
):
    theme = tmp_path / "matrix"
    theme.mkdir()
    entry = b"import './helper.js';\nexport function init() {}\n"
    (theme / "theme.json").write_text('{"id": "matrix", "effects": "effects.js"}')
    (theme / "effects.js").write_bytes(entry)
    (theme / "helper.js").write_bytes(b"export const ok = 1;\n")
    before = digest.digest_effects(theme, "effects.js")

    (theme / "helper.js").write_bytes(b"export const ok = 1; fetch('/steal');\n")
    after = digest.digest_effects(theme, "effects.js")

    assert (theme / "effects.js").read_bytes() == entry, "the entry point must not move"
    assert before != after

    verdict = consent.decide(
        declares_script=True,
        source=consent.SOURCE_USER,
        served_digest=after,
        record={"decision": "always", "digest": before},
    )
    assert verdict.may_run is False
    assert verdict.outcome == consent.PROMPT_CHANGED


def test_a_grant_recorded_under_the_retired_per_file_scheme_is_re_asked(tmp_path):
    import hashlib

    theme = tmp_path / "matrix"
    theme.mkdir()
    body = b"export function init() {}\n"
    (theme / "effects.js").write_bytes(body)
    (theme / "theme.json").write_text('{"id": "matrix", "effects": "effects.js"}')

    old_scheme_grant = hashlib.sha256(body).hexdigest()
    served = digest.digest_effects(theme, "effects.js")
    assert served != old_scheme_grant

    verdict = consent.decide(
        declares_script=True,
        source=consent.SOURCE_USER,
        served_digest=served,
        record={"decision": "always", "digest": old_scheme_grant},
    )
    assert verdict.may_run is False, "an old-scheme grant must authorise nothing"
    assert verdict.outcome == consent.PROMPT_CHANGED


def test_editing_the_file_moves_the_digest(tmp_path):
    theme = tmp_path / "matrix"
    theme.mkdir()
    script = theme / "effects.js"
    script.write_bytes(b"export function init() {}\n")
    before = digest.digest_effects(theme, "effects.js")
    script.write_bytes(b"export function init() { steal(); }\n")
    after = digest.digest_effects(theme, "effects.js")
    assert before != after

    verdict = consent.decide(
        declares_script=True,
        source=consent.SOURCE_USER,
        served_digest=after,
        record={"decision": "always", "digest": before},
    )
    assert verdict.may_run is False
    assert verdict.outcome == consent.PROMPT_CHANGED


def test_a_missing_file_answers_none_not_a_digest_of_nothing(tmp_path):
    theme = tmp_path / "matrix"
    theme.mkdir()
    assert digest.digest_effects(theme, "effects.js") is None


def test_a_theme_that_declares_no_script_answers_none(tmp_path):
    theme = tmp_path / "matrix"
    theme.mkdir()
    assert digest.digest_effects(theme, None) is None
    assert digest.digest_effects(theme, "") is None


def test_a_filename_with_a_path_in_it_is_refused(tmp_path):
    theme = tmp_path / "matrix"
    theme.mkdir()
    (theme / "effects.js").write_bytes(b"x")
    outside = tmp_path / "secret.js"
    outside.write_bytes(b"secret")
    assert digest.digest_effects(theme, "../secret.js") is None
    assert digest.digest_effects(theme, "sub/effects.js") is None


def test_an_oversized_script_answers_none(tmp_path, monkeypatch):
    theme = tmp_path / "matrix"
    theme.mkdir()
    (theme / "effects.js").write_bytes(b"x" * 128)
    monkeypatch.setattr(digest, "MAX_EFFECTS_BYTES", 16)
    assert digest.digest_effects(theme, "effects.js") is None


def test_an_oversized_folder_answers_none(tmp_path, monkeypatch):
    theme = tmp_path / "matrix"
    theme.mkdir()
    (theme / "effects.js").write_bytes(b"x" * 8)
    (theme / "huge.bin").write_bytes(b"y" * 4096)
    monkeypatch.setattr(digest, "MAX_THEME_FOLDER_BYTES", 64)
    assert digest.digest_effects(theme, "effects.js") is None


def test_an_empty_folder_answers_none_rather_than_a_shared_hash(tmp_path):
    theme = tmp_path / "matrix"
    theme.mkdir()
    assert digest.digest_theme_folder(theme) is None
