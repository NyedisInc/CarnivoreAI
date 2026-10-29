
from __future__ import annotations

import hashlib

import pytest

from src.core.message_model_secrets import (
    ALL_DETECTORS,
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_OP_SERVICE_ACCOUNT,
    MIN_ENTROPY_BITS_PER_CHAR,
    REFERENCE_PREFIXES,
    SecretFinding,
    scan_text,
    shannon_entropy,
)

FAKE_OP_TOKEN = "ops_" + "eyJzaWduSW5BZGRyZXNzIjoiRVhBTVBMRSIsInVzZXIiOiJ4In0K" * 2

FAKE_API_KEY = "sk9Q" "vR2mXt7ZbL4nHw8KdJ3aYcE6fUgP"


def test_an_ops_token_is_detected():
    findings = scan_text(f'{{"env":"OP_SERVICE_ACCOUNT_TOKEN={FAKE_OP_TOKEN}"}}')
    assert [f.detector for f in findings] == [DETECTOR_OP_SERVICE_ACCOUNT]


def test_one_credential_produces_one_finding_not_two():
    findings = scan_text(f"OP_SERVICE_ACCOUNT_TOKEN={FAKE_OP_TOKEN}")
    assert len(findings) == 1


def test_the_literal_word_ops_in_prose_does_not_match():
    assert scan_text("we moved ops_ into the firridge") == []


def test_a_high_entropy_credential_assignment_is_detected():
    findings = scan_text(f'"api_key": "{FAKE_API_KEY}"')
    assert [f.detector for f in findings] == [DETECTOR_HIGH_ENTROPY_ASSIGNMENT]


def test_every_credential_word_fires_the_assignment_detector():
    for name in ("TOKEN", "SECRET", "KEY", "PASSWORD", "GITSERVER_API_TOKEN"):
        findings = scan_text(f"{name}={FAKE_API_KEY}")
        assert findings, f"{name} did not fire the assignment detector"


def test_an_op_reference_is_not_a_secret():
    for prefix in REFERENCE_PREFIXES:
        assert scan_text(f'"api_token": "{prefix}Claude/Item/field"') == []


def test_the_reference_test_has_a_positive_control():
    assert scan_text(f'"api_token": "{FAKE_API_KEY}"')


def test_a_low_entropy_value_under_a_credential_name_is_not_flagged():
    assert scan_text("password=aaaaaaaaaaaaaaaaaaaaaaaa") == []


def test_a_long_identifier_that_is_not_a_credential_name_is_not_flagged():
    assert scan_text(f"module_path={FAKE_API_KEY}") == []


def test_a_name_that_merely_contains_a_credential_word_is_not_flagged():
    assert scan_text(f"KEYBOARD_LAYOUT_ID={FAKE_API_KEY}") == []


def test_no_finding_field_can_carry_the_matched_value():
    findings = scan_text(f"token={FAKE_API_KEY}")
    assert findings
    for finding in findings:
        for value in vars(finding).values():
            assert FAKE_API_KEY not in str(value)


def test_the_hash_identifies_the_same_credential_across_records():
    one = scan_text(f"token={FAKE_API_KEY}")[0]
    two = scan_text(f'{{"secret":"{FAKE_API_KEY}"}}')[0]
    assert one.value_sha256 == two.value_sha256
    assert one.value_sha256 == hashlib.sha256(
        FAKE_API_KEY.encode("utf-8")).hexdigest()


def test_findings_come_back_in_offset_order():
    text = f"a=1 token={FAKE_API_KEY} then {FAKE_OP_TOKEN} end"
    offsets = [f.offset for f in scan_text(text)]
    assert offsets == sorted(offsets)


def test_entropy_of_a_repeated_character_is_zero():
    assert shannon_entropy("aaaa") == 0.0


def test_entropy_of_a_credential_shaped_string_clears_the_threshold():
    assert shannon_entropy(FAKE_API_KEY) > MIN_ENTROPY_BITS_PER_CHAR


def test_entropy_of_an_empty_string_is_zero_rather_than_an_error():
    assert shannon_entropy("") == 0.0


def test_a_finding_rejects_an_unregistered_detector():
    with pytest.raises(ValueError):
        SecretFinding("not_a_detector", 0, 1, "x")


def test_a_finding_rejects_a_zero_length_match():
    with pytest.raises(ValueError):
        SecretFinding(ALL_DETECTORS[0], 0, 0, "x")


def test_scanning_ordinary_prose_finds_nothing():
    assert scan_text(
        "The backup ran at 04:00 and captured 25.7 GiB across seven groups."
    ) == []


def test_a_long_run_of_word_characters_scans_in_linear_time():
    import time

    run = "z" * 8192
    started = time.perf_counter()
    scan_text(run)
    assert time.perf_counter() - started < 1.0


def test_bounding_the_name_does_not_lose_a_long_credential_name():
    long_name = "service." * 12 + "api_key"
    findings = scan_text(f"{long_name}={FAKE_API_KEY}")
    assert [f.detector for f in findings] == [DETECTOR_HIGH_ENTROPY_ASSIGNMENT]
    assert findings[0].length == len(FAKE_API_KEY)
