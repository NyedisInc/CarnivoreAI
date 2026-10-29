
from __future__ import annotations

import pytest

from src.core.message_model_secrets import (
    ALL_DETECTORS,
    DETECTOR_ANTHROPIC_API_KEY,
    DETECTOR_CARNIVORE_API_KEY,
    DETECTOR_CATALOG_BOT_TOKEN,
    DETECTOR_AWS_ACCESS_KEY_ID,
    DETECTOR_AWS_SECRET_ACCESS_KEY,
    DETECTOR_BEARER_TOKEN,
    DETECTOR_JWT,
    DETECTOR_CLOUDFLARE_API_TOKEN,
    DETECTOR_GITHUB_TOKEN,
    DETECTOR_GOOGLE_API_KEY,
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_OPENAI_API_KEY,
    DETECTOR_PEM_PRIVATE_KEY,
    DETECTOR_GITLAB_TOKEN,
    DETECTOR_HUGGINGFACE_TOKEN,
    DETECTOR_NPM_TOKEN,
    DETECTOR_SENDGRID_KEY,
    DETECTOR_SLACK_APP_TOKEN,
    DETECTOR_SLACK_TOKEN,
    DETECTOR_STRIPE_KEY,
    VENDOR_DETECTORS,
    has_mixed_alphabet,
    is_placeholder,
    scan_text,
)
from tests.synthetic_credentials import (
    ANTHROPIC_PREFIXES,
    OPENAI_PREFIXES,
    anthropic_key,
    aws_key_id,
    aws_secret_key,
    github_fine_grained_token,
    github_token,
    google_api_key,
    openai_key,
    slack_bot_token,
    synthetic_body,
)

FAKE_GITHUB = github_token()
FAKE_GITHUB_FINE = github_fine_grained_token()
FAKE_AWS_ID = aws_key_id()
FAKE_AWS_SECRET = aws_secret_key()
FAKE_GOOGLE = google_api_key()
FAKE_SLACK = slack_bot_token()
FAKE_CLOUDFLARE = synthetic_body(37)
FAKE_MINISIGN_SECRET = (
    "untrusted comment: minisign encrypted secret key\n"
    "RWRCSwYpTm3xKd7QvZa9HcJ6wLbNfSgU4hEoMrX1\n"  # secret-scan: allow synthetic fixture, not an issued credential
)

FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + synthetic_body(60)
    + "\n"
    "-----END RSA PRIVATE KEY-----\n"
)

def _synthetic_segment(seed: str, size: int) -> str:
    import base64
    import hashlib

    raw = hashlib.sha256(seed.encode()).digest() * 2
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")[:size]


FAKE_BEARER = _synthetic_segment("bearer", 40)
FAKE_JWT = ".".join(
    ["eyJ" + _synthetic_segment("h", 24), "eyJ" + _synthetic_segment("p", 24), _synthetic_segment("s", 30)]
)

def _alnum(seed: str, size: int) -> str:
    return "".join(c for c in _synthetic_segment(seed, 200) if c.isalnum())[:size]


FAKE_STRIPE = "sk_" + "live_" + _alnum("stripe", 28)
FAKE_HF = "hf_" + _alnum("hf", 34)
FAKE_NPM = "npm_" + _alnum("npm", 36)
FAKE_GITLAB = "glpat-" + _alnum("gitlab", 22)
FAKE_SENDGRID = "SG." + _alnum("sg1", 22) + "." + _alnum("sg2", 43)
FAKE_SLACK_APP = "xapp-1-" + _alnum("xapp", 30)
FAKE_CAK = "cak_" + _alnum("cak", 43)
FAKE_CBT = "cbt_" + _alnum("cbt", 43)

CASES = {
    DETECTOR_STRIPE_KEY: (f"charge with {FAKE_STRIPE} now", ["sk_live_short", "ask_live_" + "x" * 5]),
    DETECTOR_HUGGINGFACE_TOKEN: (f"login {FAKE_HF}", ["hf_short", "hf_" + "a" * 34]),
    DETECTOR_NPM_TOKEN: (f"//registry:_authToken {FAKE_NPM}", ["npm_install", "npm_" + "a" * 36]),
    DETECTOR_GITLAB_TOKEN: (f"use {FAKE_GITLAB} here", ["glpat-short", "glpat-" + "a" * 22]),
    DETECTOR_SENDGRID_KEY: (f"key {FAKE_SENDGRID} end", ["SG.short.short", "SG.x"]),
    DETECTOR_SLACK_APP_TOKEN: (f"app {FAKE_SLACK_APP} end", ["xapp-short", "the xapp-"]),
    DETECTOR_CARNIVORE_API_KEY: (
        f"CARNIVORE_API_KEY={FAKE_CAK}",
        ["cak_short", "cak_" + "a" * 43, "CARNIVORE_API_KEY=op://Claude/Carnivore/api_key", "CARNIVORE_API_KEY=${CARNIVORE_API_KEY}"],
    ),
    DETECTOR_CATALOG_BOT_TOKEN: (
        f"CARNIVORE_CATALOG_TOKEN={FAKE_CBT}",
        ["cbt_short", "cbt_" + "a" * 43, "CARNIVORE_CATALOG_TOKEN=${CARNIVORE_CATALOG_TOKEN}"],
    ),
    DETECTOR_BEARER_TOKEN: (
        f"Authorization: Bearer {FAKE_BEARER}",
        [
            "Authorization: Bearer ${TOKEN}",
            "Authorization: Bearer <token>",
            "the bearer of good news",
        ],
    ),
    DETECTOR_JWT: (
        f"session {FAKE_JWT} end",
        ["eyJ.eyJ.x", "some.module.path.eyJ"],
    ),
    DETECTOR_GITHUB_TOKEN: (
        f"GITHUB_TOKEN={FAKE_GITHUB}",
        [
            "GITHUB_TOKEN=ghp_YOUR_PERSONAL_ACCESS_TOKEN_GOES_HERE_xx",
            "GITHUB_TOKEN=op://Claude/GitHub/personal_access_token",
            'GITHUB_TOKEN=${GH_TOKEN}',
            'github_token = os.environ["GH_TOKEN"]',
        ],
    ),
    DETECTOR_AWS_ACCESS_KEY_ID: (
        f"AWS_ACCESS_KEY_ID={FAKE_AWS_ID}",
        [
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
            "AWS_ACCESS_KEY_ID=op://Claude/AWS/access_key_id",
            "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}",
        ],
    ),
    DETECTOR_AWS_SECRET_ACCESS_KEY: (
        f"AWS_SECRET_ACCESS_KEY={FAKE_AWS_SECRET}",
        [
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "AWS_SECRET_ACCESS_KEY=op://Claude/AWS/secret_access_key",
            "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}",
        ],
    ),
    DETECTOR_GOOGLE_API_KEY: (
        f"GOOGLE_API_KEY={FAKE_GOOGLE}",
        [
            "GOOGLE_API_KEY=AIzaSyYOUR_GOOGLE_API_KEY_HERE_00000000",
            "GOOGLE_API_KEY=op://Claude/Google/api_key",
            "GOOGLE_API_KEY=${GOOGLE_API_KEY}",
        ],
    ),
    DETECTOR_SLACK_TOKEN: (
        f"SLACK_BOT_TOKEN={FAKE_SLACK}",
        [
            "SLACK_BOT_TOKEN=xoxb-0000000000-0000000000-YOUR-TOKEN-HERE",
            "SLACK_BOT_TOKEN=op://Claude/Slack/bot_token",
            "SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}",
        ],
    ),
    DETECTOR_CLOUDFLARE_API_TOKEN: (
        f"CLOUDFLARE_API_TOKEN={FAKE_CLOUDFLARE}",
        [
            "CLOUDFLARE_API_TOKEN=your-cloudflare-api-token-goes-here00",
            "CLOUDFLARE_API_TOKEN=op://Claude/Cloudflare/api_token",
            "CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}",
            'CF_API_TOKEN = process.env.CF_API_TOKEN',
        ],
    ),
    DETECTOR_MINISIGN_SECRET_KEY: (
        FAKE_MINISIGN_SECRET,
        [
            "untrusted comment: minisign encrypted secret key\n",
            "the key file opens with untrusted comment: minisign "
            "encrypted secret key on line one",
            "minisign_secret_key = op://Claude/Carnivore/minisign_secret_key",
        ],
    ),
    DETECTOR_ANTHROPIC_API_KEY: (
        f"ANTHROPIC_API_KEY={anthropic_key()}",
        [
            f"ANTHROPIC_API_KEY={ANTHROPIC_PREFIXES[0]}YOUR_API_KEY_HERE_0000000000000000",
            "ANTHROPIC_API_KEY=op://Claude/Anthropic/api_key",
            "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}",
            f"keys start with {ANTHROPIC_PREFIXES[0]} and are long",
        ],
    ),
    DETECTOR_OPENAI_API_KEY: (
        f"OPENAI_API_KEY={openai_key()}",
        [
            f"OPENAI_API_KEY={OPENAI_PREFIXES[0]}your-project-key-goes-here-000000000000",
            "OPENAI_API_KEY=op://Claude/OpenAI/api_key",
            "OPENAI_API_KEY=${OPENAI_API_KEY}",
            f"project keys start with {OPENAI_PREFIXES[0]} and are long",
        ],
    ),
    DETECTOR_PEM_PRIVATE_KEY: (
        FAKE_PEM,
        [
            "-----BEGIN OPENSSH PRIVATE KEY-----\n",
            "the file starts with -----BEGIN RSA PRIVATE KEY----- as expected",
            "private_key = op://Claude/Host/private_key",
        ],
    ),
}


@pytest.mark.parametrize("detector", sorted(CASES))
def test_the_detector_fires_on_a_synthetic_credential(detector):
    positive = CASES[detector][0]
    fired = {f.detector for f in scan_text(positive)}
    assert detector in fired, f"{detector} did not fire on its own sample"


@pytest.mark.parametrize(
    "detector,sample",
    [(d, s) for d, (_, negatives) in CASES.items() for s in negatives],
    ids=lambda v: str(v)[:48],
)
def test_a_placeholder_reference_or_indirection_is_not_a_secret(
    detector, sample,
):
    fired = {f.detector for f in scan_text(sample)}
    assert detector not in fired, f"{detector} false-positived on {sample!r}"


@pytest.mark.parametrize("detector", sorted(CASES))
def test_one_credential_produces_exactly_one_finding(detector):
    assert len(scan_text(CASES[detector][0])) == 1


@pytest.mark.parametrize("detector", sorted(CASES))
def test_no_finding_field_can_carry_the_matched_value(detector):
    positive = CASES[detector][0]
    findings = scan_text(positive)
    assert findings
    payload = positive.split("=", 1)[-1].strip()
    for finding in findings:
        for value in vars(finding).values():
            assert payload not in str(value)


def test_every_declared_detector_has_a_case_or_is_the_generic_one():
    covered = set(CASES) | {
        DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
        "op_service_account_token",
    }
    assert set(ALL_DETECTORS) <= covered


def test_the_vendor_set_excludes_the_generic_assignment_detector():
    assert DETECTOR_HIGH_ENTROPY_ASSIGNMENT not in VENDOR_DETECTORS


def test_a_bare_pem_header_with_no_key_material_is_not_a_key():
    assert scan_text('write_text("-----BEGIN OPENSSH PRIVATE KEY-----\\n")') == []
    assert scan_text(FAKE_PEM), "positive control: a real block still fires"


def test_a_minisign_secret_key_header_fires_and_keeps_the_body_out():
    findings = scan_text(FAKE_MINISIGN_SECRET)
    assert [f.detector for f in findings] == [DETECTOR_MINISIGN_SECRET_KEY]
    body = FAKE_MINISIGN_SECRET.splitlines()[1]
    for finding in findings:
        for value in vars(finding).values():
            assert body not in str(value)
    assert findings[0].length == len(
        "untrusted comment: minisign encrypted secret key"
    ), "the match must stop at the header, never run into the body"


def test_ops_inside_an_identifier_is_not_a_service_account_token():
    assert scan_text(
        "async def test_router_drops_emit_when_all_three_channels_unconfigured():"
    ) == []


def test_a_fine_grained_github_token_fires_and_keeps_the_value_out():
    findings = scan_text(
        f"GITHUB_TOKEN={FAKE_GITHUB_FINE}", detectors=[DETECTOR_GITHUB_TOKEN]
    )
    assert findings, "the fine-grained token shape was not detected"
    assert all(
        FAKE_GITHUB_FINE not in str(getattr(finding, field, ""))
        for finding in findings
        for field in finding.__dataclass_fields__
    ), "a finding field carried the matched token"


def test_a_fine_grained_placeholder_is_not_a_secret():
    assert not scan_text(
        "GITHUB_TOKEN=github_pat_YOUR_FINE_GRAINED_TOKEN_GOES_HERE",
        detectors=[DETECTOR_GITHUB_TOKEN],
    )


def test_mixed_alphabet_separates_a_payload_from_an_identifier():
    assert has_mixed_alphabet(FAKE_GITHUB)
    assert not has_mixed_alphabet("emit_when_all_three_channels_unconfigured")


def test_is_placeholder_covers_all_three_rejection_reasons():
    assert is_placeholder("op://Claude/Item/field")
    assert is_placeholder("${CF_API_TOKEN}")
    assert is_placeholder("ghp_" + "x" * 36)
    assert is_placeholder("YOUR_TOKEN_HERE_0000000000000000000000")
    assert not is_placeholder(FAKE_GITHUB), "positive control"


def test_narrowing_the_detector_set_narrows_the_findings():
    text = f"GITHUB_TOKEN={FAKE_GITHUB}"
    assert scan_text(text, detectors=[DETECTOR_GITHUB_TOKEN])
    assert scan_text(text, detectors=[DETECTOR_SLACK_TOKEN]) == []


def test_an_unknown_detector_name_is_refused_rather_than_ignored():
    with pytest.raises(ValueError):
        scan_text("anything", detectors=["not_a_detector"])


@pytest.mark.parametrize("prefix", ANTHROPIC_PREFIXES)
def test_every_anthropic_key_family_is_detected(prefix):
    key = anthropic_key(prefix)
    findings = scan_text(f"echo {key}\n")
    assert [f.detector for f in findings] == [DETECTOR_ANTHROPIC_API_KEY]
    assert findings[0].length == len(key)


@pytest.mark.parametrize("prefix", OPENAI_PREFIXES)
def test_every_openai_project_service_and_admin_key_is_detected(prefix):
    key = openai_key(prefix)
    findings = scan_text(f"{key}\n")
    assert [f.detector for f in findings] == [DETECTOR_OPENAI_API_KEY]
    assert findings[0].length == len(key)


def test_example_substring_does_not_make_a_real_credential_a_placeholder():
    aws_id = "AKIA" + "QZ7M3VKD" + "EXAMPLE" + "9"
    assert len(aws_id) == 20
    assert not is_placeholder(aws_id)
    findings = scan_text("AWS_ACCESS_KEY_ID=" + aws_id)
    assert any(f.detector == DETECTOR_AWS_ACCESS_KEY_ID for f in findings)
    assert is_placeholder("AKIAIOSFODNN7EXAMPLE")
    assert not is_placeholder("AKIAIOSFODNN7EXAMPL" + "F")
