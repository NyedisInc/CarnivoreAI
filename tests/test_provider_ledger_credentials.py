
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest
import structlog.testing

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.provider_ledger import credentials, keychain

FAKE_CLAUDE_TOKEN = "sk-ant-oat01-NOT-A-REAL-TOKEN"

DEFAULT_SERVICE = "Claude Code-credentials"

TEST_USER = "fixture-user"

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _claude_blob(
    *,
    expires_at: Optional[datetime] = None,
    refresh_token_expires_at: Optional[datetime] = None,
    scopes: Optional[List[str]] = None,
    token: str = FAKE_CLAUDE_TOKEN,
) -> str:
    oauth: dict = {
        "accessToken": token,
        "refreshToken": "sk-ant-ort01-NOT-A-REAL-TOKEN",
        "subscriptionType": "max",
        "rateLimitTier": "default_claude_max_20x",
    }
    if expires_at is not None:
        oauth["expiresAt"] = _ms(expires_at)
    if refresh_token_expires_at is not None:
        oauth["refreshTokenExpiresAt"] = _ms(refresh_token_expires_at)
    if scopes is not None:
        oauth["scopes"] = scopes
    return json.dumps({"claudeAiOauth": oauth})


def _jwt(payload: dict) -> str:

    def segment(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(payload)}."


def _codex_claims(*, exp: datetime, plan: str = "plus") -> dict:
    return {
        "email": "alex@example.invalid",
        "exp": int(exp.timestamp()),
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-from-claim",
            "chatgpt_plan_type": plan,
        },
    }


class _Run:

    def __init__(self, outcomes: List[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: List[List[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        outcome = self.outcomes.pop(0) if self.outcomes else (1, "")
        if isinstance(outcome, BaseException):
            raise outcome
        code, stdout = outcome
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="")


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USER", TEST_USER)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return tmp_path




def test_the_default_config_dir_has_exactly_one_service_name(home) -> None:
    assert credentials.claude_keychain_services("~/.claude") == [DEFAULT_SERVICE]


def test_the_default_dir_spelled_absolutely_is_still_the_default(home) -> None:
    absolute = str(home / ".claude")
    assert credentials.claude_keychain_services(absolute) == [DEFAULT_SERVICE]


def test_a_custom_config_dir_tries_both_disputed_suffixes(home) -> None:
    raw = "~/.claude-work"
    expanded = os.path.expanduser(raw)
    (home / ".claude-work").mkdir()
    raw_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    real_hash = hashlib.sha256(os.path.realpath(expanded).encode()).hexdigest()[:8]

    services = credentials.claude_keychain_services(raw)

    assert services == [
        f"{DEFAULT_SERVICE}-{raw_hash}",
        f"{DEFAULT_SERVICE}-{real_hash}",
    ]


def test_a_custom_dir_whose_two_hashes_agree_yields_one_candidate(home) -> None:
    absolute = str((home / ".claude-work").resolve())
    (home / ".claude-work").mkdir()
    services = credentials.claude_keychain_services(absolute)
    assert len(services) == len(set(services))
    assert len(services) == 1


def test_the_default_dir_never_borrows_a_suffixed_item(home) -> None:
    (home / ".claude-work").mkdir()
    assert DEFAULT_SERVICE not in credentials.claude_keychain_services("~/.claude-work")




def test_the_keychain_is_asked_with_the_exact_documented_argv(home, monkeypatch) -> None:
    runner = _Run([(0, _claude_blob(expires_at=datetime.now(timezone.utc) + timedelta(hours=1)) + "\n")])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    credentials.read_claude_credential("~/.claude")

    assert runner.calls == [
        ["security", "find-generic-password", "-s", DEFAULT_SERVICE, "-a", TEST_USER, "-w"]
    ]


def test_a_keychain_hit_is_parsed_into_the_credential(home, monkeypatch) -> None:
    expires = NOW + timedelta(hours=3)
    runner = _Run([(0, _claude_blob(expires_at=expires, scopes=["user:inference", "user:profile"]))])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None
    assert cred.access_token == FAKE_CLAUDE_TOKEN
    assert cred.expires_at == expires.replace(microsecond=0)
    assert cred.expires_at.tzinfo is not None
    assert cred.scopes == ("user:inference", "user:profile")
    assert cred.subscription_type == "max"
    assert cred.rate_limit_tier == "default_claude_max_20x"
    assert cred.source == "keychain"


def test_both_candidate_services_are_tried_in_order(home, monkeypatch) -> None:
    (home / ".claude-work").mkdir()
    runner = _Run([(1, ""), (1, ""), (0, _claude_blob())])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    cred = credentials.read_claude_credential("~/.claude-work")

    assert cred is not None
    expected = credentials.claude_keychain_services("~/.claude-work")
    asked = [call[call.index("-s") + 1] for call in runner.calls]
    assert list(dict.fromkeys(asked)) == expected
    assert runner.calls[0][-3:] == ["-a", TEST_USER, "-w"]
    assert "-a" not in runner.calls[1]


def test_a_custom_profile_never_borrows_the_default_login(home, monkeypatch) -> None:
    asked: List[str] = []

    def answer(argv, **kwargs):
        service = argv[argv.index("-s") + 1]
        asked.append(service)
        if service == DEFAULT_SERVICE:
            return subprocess.CompletedProcess(argv, 0, stdout=_claude_blob(), stderr="")
        return subprocess.CompletedProcess(argv, 44, stdout="", stderr="")

    monkeypatch.setattr(keychain.subprocess, "run", answer)

    cred = credentials.read_claude_credential("~/.claude-does-not-exist")

    assert cred is None
    assert credentials.credential_state_for(cred, NOW) == "missing"
    assert DEFAULT_SERVICE not in asked
    assert list(dict.fromkeys(asked)) == credentials.claude_keychain_services(
        "~/.claude-does-not-exist"
    )


def test_a_keychain_miss_falls_back_to_the_credentials_file(home, monkeypatch) -> None:
    config_dir = home / ".claude"
    config_dir.mkdir()
    (config_dir / ".credentials.json").write_text(_claude_blob())
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(1, "")]))

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None
    assert cred.source == "file"


def test_nothing_anywhere_reads_as_none(home, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(1, "")]))
    assert credentials.read_claude_credential("~/.claude") is None


def test_a_keychain_timeout_does_not_stop_the_file_fallback(home, monkeypatch) -> None:
    config_dir = home / ".claude"
    config_dir.mkdir()
    (config_dir / ".credentials.json").write_text(_claude_blob())
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        _Run([subprocess.TimeoutExpired(cmd="security", timeout=5)]),
    )

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None
    assert cred.source == "file"


def test_an_item_holding_no_oauth_block_is_not_a_credential(home, monkeypatch) -> None:
    monkeypatch.setattr(
        keychain.subprocess, "run", _Run([(0, json.dumps({"mcpOAuth": {}}))])
    )
    assert credentials.read_claude_credential("~/.claude") is None


def test_an_unparseable_item_is_not_a_credential(home, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(0, "{not json")]))
    assert credentials.read_claude_credential("~/.claude") is None


def test_no_log_line_anywhere_carries_the_token(home, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(0, _claude_blob())]))
    with structlog.testing.capture_logs() as captured:
        credentials.read_claude_credential("~/.claude")
    assert FAKE_CLAUDE_TOKEN not in json.dumps(captured)


def test_a_failed_keychain_read_logs_its_status_and_not_its_output(
    home, monkeypatch
) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(44, "")]))
    with structlog.testing.capture_logs() as captured:
        credentials.read_claude_credential("~/.claude")
    misses = [e for e in captured if e["event"] == "keychain_read_failed"]
    assert misses and misses[0]["status"] == 44
    assert misses[0]["service"] == DEFAULT_SERVICE




def test_the_claude_credential_repr_hides_the_token(home, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(0, _claude_blob())]))
    cred = credentials.read_claude_credential("~/.claude")
    assert FAKE_CLAUDE_TOKEN not in repr(cred)
    assert FAKE_CLAUDE_TOKEN not in str(cred)
    assert "ClaudeCredential" in repr(cred)


def test_the_codex_credential_repr_hides_both_tokens(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    access = _jwt({"exp": int((NOW + timedelta(hours=1)).timestamp())})
    ident = _jwt(_codex_claims(exp=NOW + timedelta(hours=1)))
    (codex_home / "auth.json").write_text(
        json.dumps({"tokens": {"access_token": access, "id_token": ident}})
    )
    cred = credentials.read_codex_credential(str(codex_home))
    assert cred is not None
    assert access not in repr(cred) and access not in str(cred)
    assert ident not in repr(cred) and ident not in str(cred)




def test_no_credential_is_missing() -> None:
    assert credentials.credential_state_for(None, NOW) == "missing"


def test_a_lapsed_expiry_is_expired(home, monkeypatch) -> None:
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        _Run([(0, _claude_blob(expires_at=NOW - timedelta(minutes=1)))]),
    )
    cred = credentials.read_claude_credential("~/.claude")
    assert credentials.credential_state_for(cred, NOW) == "expired"


def test_a_token_without_the_profile_scope_is_refused(home, monkeypatch) -> None:
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        _Run([(0, _claude_blob(expires_at=NOW + timedelta(hours=1), scopes=["user:inference"]))]),
    )
    cred = credentials.read_claude_credential("~/.claude")
    assert credentials.credential_state_for(cred, NOW) == "refused"


def test_a_live_credential_with_the_scope_is_ok(home, monkeypatch) -> None:
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        _Run(
            [
                (
                    0,
                    _claude_blob(
                        expires_at=NOW + timedelta(hours=1),
                        scopes=["user:inference", "user:profile"],
                    ),
                )
            ]
        ),
    )
    cred = credentials.read_claude_credential("~/.claude")
    assert credentials.credential_state_for(cred, NOW) == "ok"


def test_an_absent_scope_list_is_not_a_refusal(home, monkeypatch) -> None:
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        _Run([(0, _claude_blob(expires_at=NOW + timedelta(hours=1)))]),
    )
    cred = credentials.read_claude_credential("~/.claude")
    assert credentials.credential_state_for(cred, NOW) == "ok"



NON_ASCII = "é"
NON_ASCII_ESCAPE = "\\xe9"


def test_a_token_that_cannot_be_sent_as_a_header_is_an_error_state() -> None:
    cred = credentials.ClaudeCredential(
        access_token=FAKE_CLAUDE_TOKEN + NON_ASCII,
        expires_at=NOW + timedelta(hours=1),
        refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:inference", "user:profile"),
        subscription_type="max",
        rate_limit_tier="default",
        source="keychain",
    )
    assert credentials.credential_state_for(cred, NOW) == "error"


def test_a_codex_account_id_that_cannot_be_sent_is_an_error_state_too() -> None:
    cred = credentials.CodexCredential(
        access_token="ey-codex-NOT-A-REAL-TOKEN",
        id_token=None,
        account_id="acct-" + NON_ASCII,
        plan="plus",
        email="someone@example.test",
        last_refresh=None,
        expires_at=NOW + timedelta(hours=1),
        source="file",
    )
    assert credentials.credential_state_for(cred, NOW) == "error"


def test_the_refusal_names_no_part_of_the_value_it_refused() -> None:
    cred = credentials.ClaudeCredential(
        access_token=FAKE_CLAUDE_TOKEN + NON_ASCII,
        expires_at=NOW + timedelta(hours=1),
        refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:inference", "user:profile"),
        subscription_type="max",
        rate_limit_tier="default",
        source="keychain",
    )

    with structlog.testing.capture_logs() as captured:
        credentials.credential_state_for(cred, NOW)

    assert any("not_transmittable" in str(r.get("event")) for r in captured)
    rendered = repr(captured)
    assert FAKE_CLAUDE_TOKEN not in rendered
    assert NON_ASCII not in rendered
    assert NON_ASCII_ESCAPE not in rendered


def test_an_expiry_that_has_lapsed_still_wins_over_the_header_rule() -> None:
    cred = credentials.ClaudeCredential(
        access_token=FAKE_CLAUDE_TOKEN + NON_ASCII,
        expires_at=NOW - timedelta(minutes=1),
        refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:inference", "user:profile"),
        subscription_type="max",
        rate_limit_tier="default",
        source="keychain",
    )
    assert credentials.credential_state_for(cred, NOW) == "expired"




NOT_UTF8 = b"\xff\xfe{\x00\"claudeAiOauth\x00\"}"


def test_a_claude_credential_file_that_is_not_utf8_reads_as_nothing(
    home, monkeypatch
) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(1, "")]))
    config_dir = home / ".claude"
    config_dir.mkdir()
    (config_dir / credentials.CLAUDE_CREDENTIALS_FILE).write_bytes(NOT_UTF8)

    with structlog.testing.capture_logs() as captured:
        assert credentials.read_claude_credential("~/.claude") is None

    assert any("unreadable" in str(record.get("event")) for record in captured)


def test_a_claude_identity_file_that_is_not_utf8_reads_as_nothing(home) -> None:
    (home / credentials.CLAUDE_IDENTITY_FILE).write_bytes(NOT_UTF8)

    assert credentials.read_claude_identity("~/.claude") is None


def test_a_codex_auth_file_that_is_not_utf8_reads_as_nothing(home) -> None:
    codex_home = home / ".codex"
    codex_home.mkdir()
    (codex_home / credentials.CODEX_AUTH_FILE).write_bytes(NOT_UTF8)

    with structlog.testing.capture_logs() as captured:
        assert credentials.read_codex_credential(str(codex_home)) is None

    assert any("unreadable" in str(record.get("event")) for record in captured)


def test_the_unreadable_log_line_carries_no_byte_of_the_file(home, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(1, "")]))
    config_dir = home / ".claude"
    config_dir.mkdir()
    (config_dir / credentials.CLAUDE_CREDENTIALS_FILE).write_bytes(NOT_UTF8)

    with structlog.testing.capture_logs() as captured:
        credentials.read_claude_credential("~/.claude")

    assert captured, "the read logged nothing, so the search proves nothing"
    assert "0xff" not in repr(captured)




def test_the_default_profile_reads_the_identity_from_home(home) -> None:
    (home / ".claude").mkdir()
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "emailAddress": "alex@example.invalid",
                    "organizationName": "Alex's Organization",
                    "subscriptionType": "max",
                }
            }
        )
    )
    identity = credentials.read_claude_identity("~/.claude")
    assert identity is not None
    assert identity.email == "alex@example.invalid"
    assert identity.organization_name == "Alex's Organization"
    assert identity.subscription_type == "max"


def test_a_custom_profile_reads_the_identity_from_inside_the_dir(home) -> None:
    config_dir = home / ".claude-work"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "work@example.invalid"}})
    )
    (home / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "default@example.invalid"}})
    )

    identity = credentials.read_claude_identity("~/.claude-work")

    assert identity is not None
    assert identity.email == "work@example.invalid"


def test_a_missing_identity_file_is_none(home) -> None:
    assert credentials.read_claude_identity("~/.claude") is None


def test_a_profile_that_never_logged_in_has_no_identity(home) -> None:
    config_dir = home / ".claude-cldor"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(json.dumps({"projects": {}}))
    assert credentials.read_claude_identity("~/.claude-cldor") is None


def test_an_unparseable_identity_file_is_none(home) -> None:
    (home / ".claude.json").write_text("{not json")
    assert credentials.read_claude_identity("~/.claude") is None




def _write_codex_auth(codex_home: Path, **overrides) -> dict:
    exp = overrides.pop("exp", NOW + timedelta(hours=1))
    tokens = {
        "access_token": _jwt({"exp": int(exp.timestamp())}),
        "id_token": _jwt(_codex_claims(exp=exp)),
        "refresh_token": "NOT-A-REAL-REFRESH-TOKEN",
        "account_id": "acct-from-tokens",
    }
    tokens.update(overrides.pop("tokens", {}))
    document = {
        "auth_mode": "chatgpt",
        "tokens": tokens,
        "last_refresh": "2026-09-16T02:12:14Z",
        **overrides,
    }
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "auth.json").write_text(json.dumps(document))
    return document


def test_the_codex_auth_file_is_parsed(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home)

    cred = credentials.read_codex_credential(str(codex_home))

    assert cred is not None
    assert cred.account_id == "acct-from-tokens"
    assert cred.plan == "plus"
    assert cred.email == "alex@example.invalid"
    assert cred.last_refresh == datetime(2026, 9, 16, 2, 12, 14, tzinfo=timezone.utc)
    assert cred.expires_at == NOW + timedelta(hours=1)
    assert cred.source == "file"


def test_the_account_id_falls_back_to_the_id_token_claim(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, tokens={"account_id": None})

    cred = credentials.read_codex_credential(str(codex_home))

    assert cred is not None
    assert cred.account_id == "acct-from-claim"


def test_a_missing_codex_home_is_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(keychain.subprocess, "run", _Run([(1, "")]))
    assert credentials.read_codex_credential(str(tmp_path / "nope")) is None


def test_an_unparseable_codex_auth_file_is_none(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{not json")
    assert credentials.read_codex_credential(str(codex_home)) is None


def test_a_lapsed_codex_access_token_is_expired(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, exp=NOW - timedelta(minutes=1))
    cred = credentials.read_codex_credential(str(codex_home))
    assert credentials.credential_state_for(cred, NOW) == "expired"


def test_a_live_codex_access_token_is_ok(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home)
    cred = credentials.read_codex_credential(str(codex_home))
    assert credentials.credential_state_for(cred, NOW) == "ok"


def test_a_missing_auth_file_falls_back_to_the_keychain(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    document = {
        "tokens": {
            "access_token": _jwt({"exp": int((NOW + timedelta(hours=1)).timestamp())}),
            "id_token": _jwt(_codex_claims(exp=NOW + timedelta(hours=1))),
            "account_id": "acct-from-keychain",
        }
    }
    runner = _Run([(0, json.dumps(document))])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    cred = credentials.read_codex_credential(str(codex_home))

    assert cred is not None
    assert cred.account_id == "acct-from-keychain"
    assert cred.source == "keychain"


def test_the_codex_keychain_account_is_the_documented_store_key(
    tmp_path, monkeypatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    runner = _Run([(1, "")])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    credentials.read_codex_credential(str(codex_home))

    digest = hashlib.sha256(os.path.realpath(str(codex_home)).encode()).hexdigest()
    assert runner.calls == [
        [
            "security",
            "find-generic-password",
            "-s",
            "Codex Auth",
            "-a",
            f"cli|{digest[:16]}",
            "-w",
        ]
    ]


def test_no_codex_log_line_carries_a_token(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    document = _write_codex_auth(codex_home)
    with structlog.testing.capture_logs() as captured:
        credentials.read_codex_credential(str(codex_home))
    rendered = json.dumps(captured)
    assert document["tokens"]["access_token"] not in rendered
    assert document["tokens"]["refresh_token"] not in rendered




def test_reading_a_credential_leaves_the_store_untouched(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home)
    auth_file = codex_home / "auth.json"
    before = auth_file.read_bytes()

    credentials.read_codex_credential(str(codex_home))

    assert auth_file.read_bytes() == before


def test_the_keychain_is_only_ever_read(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    runner = _Run([(1, "")])
    monkeypatch.setattr(keychain.subprocess, "run", runner)

    credentials.read_codex_credential(str(codex_home))
    credentials.read_claude_credential(str(tmp_path / ".claude"))

    for call in runner.calls:
        assert call[1] == "find-generic-password"
        assert "add-generic-password" not in call
        assert "delete-generic-password" not in call




def test_one_directory_spelled_two_ways_in_unicode_is_one_candidate(home) -> None:
    import unicodedata

    composed = unicodedata.normalize("NFC", str(home / "café-claude"))
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed

    assert credentials.claude_keychain_services(
        composed
    ) == credentials.claude_keychain_services(decomposed)


def test_the_candidate_is_the_hash_of_the_composed_string(home) -> None:
    import unicodedata

    raw = "~/.claude-café"
    digest = hashlib.sha256(
        unicodedata.normalize("NFC", raw).encode("utf-8")
    ).hexdigest()[:8]
    assert credentials.claude_keychain_services(raw)[0] == f"{DEFAULT_SERVICE}-{digest}"


def test_the_expanded_candidate_is_still_tried_for_a_tilde_row(home) -> None:
    (home / ".claude-work").mkdir()
    assert len(credentials.claude_keychain_services("~/.claude-work")) == 2


def test_the_login_deadline_is_read_out_of_the_same_document(home, monkeypatch) -> None:
    deadline = NOW + timedelta(days=29)
    runner = _Run([(0, _claude_blob(expires_at=NOW + timedelta(hours=1),
                                    refresh_token_expires_at=deadline))])

    monkeypatch.setattr(keychain.subprocess, "run", runner)

    credential = credentials.read_claude_credential("~/.claude")

    assert credential is not None
    assert credential.refresh_token_expires_at == deadline


def test_a_document_that_names_no_login_deadline_answers_none(home, monkeypatch) -> None:
    runner = _Run([(0, _claude_blob(expires_at=NOW + timedelta(hours=1)))])

    monkeypatch.setattr(keychain.subprocess, "run", runner)

    credential = credentials.read_claude_credential("~/.claude")

    assert credential is not None
    assert credential.refresh_token_expires_at is None


def test_the_repr_still_hides_the_token_now_that_it_carries_two_deadlines() -> None:
    credential = credentials.ClaudeCredential(
        access_token=FAKE_CLAUDE_TOKEN,
        expires_at=NOW + timedelta(hours=1),
        refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:profile",),
        subscription_type="max",
        rate_limit_tier="default",
        source="keychain",
    )

    rendered = repr(credential)

    assert FAKE_CLAUDE_TOKEN not in rendered
    assert "refresh_token_expires_at=" in rendered


def test_a_missing_claude_credential_is_not_respawned_until_the_login_changes_or_backoff_ends(tmp_path, monkeypatch):
    from src.core.provider_ledger import credentials as cr, miss_cache

    config_dir = str(tmp_path)
    reads = []
    blob = {"value": None}

    def fake_read(service, account=None, **_kw):
        reads.append((service, account))
        return blob["value"]

    monkeypatch.setattr(cr.keychain, "read_password", fake_read)
    clock = {"t": 1000.0}
    monkeypatch.setattr(miss_cache.time, "monotonic", lambda: clock["t"])

    assert cr.read_claude_credential(config_dir) is None
    first = len(reads)
    assert first > 0
    assert cr.read_claude_credential(config_dir) is None
    assert len(reads) == first, "a cached miss must not spawn again"

    clock["t"] += miss_cache.MISS_BACKOFF_SECONDS + 1
    assert cr.read_claude_credential(config_dir) is None
    assert len(reads) == first * 2, "backoff over: one more pass"

    blob["value"] = '{"claudeAiOauth": {"accessToken": "tok"}}'
    (tmp_path / ".claude.json").write_text("{}")
    got = cr.read_claude_credential(config_dir)
    assert got is not None and got.access_token == "tok"


def test_a_missing_codex_keychain_item_is_not_respawned_until_backoff_or_a_file_appears(tmp_path, monkeypatch):
    from src.core.provider_ledger import codex_credentials as cc, miss_cache

    reads = []
    blob = {"value": None}

    def fake_read(service, account=None, **_kw):
        reads.append((service, account))
        return blob["value"]

    monkeypatch.setattr(cc.keychain, "read_password", fake_read)
    clock = {"t": 1000.0}
    monkeypatch.setattr(miss_cache.time, "monotonic", lambda: clock["t"])

    assert cc.read_codex_credential(str(tmp_path)) is None
    assert cc.read_codex_credential(str(tmp_path)) is None
    assert len(reads) == 1, "a cached miss must not spawn again"

    clock["t"] += miss_cache.MISS_BACKOFF_SECONDS + 1
    assert cc.read_codex_credential(str(tmp_path)) is None
    assert len(reads) == 2, "backoff over: one more spawn"

    clock["t"] += miss_cache.MISS_BACKOFF_MAX_SECONDS + 1
    blob["value"] = '{"tokens": {"access_token": "tok"}}'
    got = cc.read_codex_credential(str(tmp_path))
    assert got is not None and got.access_token == "tok"
    assert cc.read_codex_credential(str(tmp_path)) is not None and len(reads) == 4


def test_a_repeated_keychain_failure_is_logged_once(monkeypatch):
    import subprocess

    from src.core.provider_ledger import keychain

    keychain._last_failure.clear()
    lines = []
    monkeypatch.setattr(keychain.logger, "info", lambda event, **kw: lines.append(("info", kw)))
    monkeypatch.setattr(keychain.logger, "debug", lambda event, **kw: lines.append(("debug", kw)))
    monkeypatch.setattr(
        keychain.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", "")
    )
    for _ in range(3):
        assert keychain.read_password("Codex Auth", account="x") is None
    assert [level for level, _ in lines] == ["info", "debug", "debug"]
