
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import structlog.testing

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plx_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plx_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.provider_ledger import codex_usage

TOKEN = "eyJhbGnotarealaccesstokenbutlongenoughtofind"

FULL_PAYLOAD = {
    "plan_type": "pro",
    "rate_limit": {
        "allowed": True,
        "limit_reached": False,
        "primary_window": {
            "used_percent": 42,
            "limit_window_seconds": 18000,
            "reset_after_seconds": 9312,
            "reset_at": 1774020000,
        },
        "secondary_window": {
            "used_percent": 7.5,
            "limit_window_seconds": 604800,
            "reset_after_seconds": 400000,
            "reset_at": 1774420000,
        },
    },
    "credits": {"has_credits": True, "unlimited": False, "balance": "12.34"},
    "account_id": "acct_notreal",
}


def segment(payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def id_token_for(claims: dict) -> str:
    header = segment({"alg": "none", "typ": "JWT"})
    return f"{header}.{segment(claims)}.notasignature"


AUTH_CLAIM = "https://api.openai.com/auth"

FULL_ID_TOKEN = id_token_for(
    {
        "email": "acme@example.com",
        AUTH_CLAIM: {
            "chatgpt_account_id": "acct_notreal",
            "chatgpt_plan_type": "plus",
            "chatgpt_user_id": "user_notreal",
        },
    }
)


def client_over(responder) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(responder), follow_redirects=False
    )


def responder_for(
    status: int, json_body: dict | None = None, text: str = "", headers: dict | None = None
):

    def respond(_request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status, json=json_body, headers=headers or {})
        return httpx.Response(status, text=text, headers=headers or {})

    return respond


class TestReadingTheIdToken:

    def test_the_account_id_comes_out_of_the_auth_claim(self):
        assert codex_usage.account_id_from_id_token(FULL_ID_TOKEN) == "acct_notreal"

    def test_the_plan_type_comes_out_of_the_same_claim(self):
        assert codex_usage.plan_type_from_id_token(FULL_ID_TOKEN) == "plus"

    def test_an_absent_claim_block_is_none_rather_than_a_guess(self):
        token = id_token_for({"email": "acme@example.com"})
        assert codex_usage.account_id_from_id_token(token) is None
        assert codex_usage.plan_type_from_id_token(token) is None

    def test_a_claim_block_that_is_not_an_object_is_none(self):
        token = id_token_for({AUTH_CLAIM: "nope"})
        assert codex_usage.account_id_from_id_token(token) is None

    def test_a_non_string_account_id_is_none(self):
        token = id_token_for({AUTH_CLAIM: {"chatgpt_account_id": 12345}})
        assert codex_usage.account_id_from_id_token(token) is None

    @pytest.mark.parametrize(
        "garbage",
        [
            "",
            "notajwt",
            "only.two",
            "a.b.c.d.e",
            "header.!!!notbase64!!!.sig",
            f"header.{segment({'a': 1})[:3]}zz.sig",
            "header." + base64.urlsafe_b64encode(b"not json").decode().rstrip("=") + ".s",
            "header." + segment({"claims": "are a list"})[:-1] + ".s",
        ],
    )
    def test_garbage_never_raises_and_answers_none(self, garbage):
        assert codex_usage.account_id_from_id_token(garbage) is None
        assert codex_usage.plan_type_from_id_token(garbage) is None

    def test_a_json_payload_that_is_not_an_object_is_none(self):
        body = base64.urlsafe_b64encode(b"[1, 2, 3]").decode().rstrip("=")
        assert codex_usage.account_id_from_id_token(f"h.{body}.s") is None


class TestTheRequest:

    def test_the_url_is_the_chatgpt_backend_usage_path(self):
        url, _headers = codex_usage.build_request(TOKEN, "acct_notreal")
        assert url == "https://chatgpt.com/backend-api/wham/usage"

    def test_the_token_rides_as_a_bearer(self):
        _url, headers = codex_usage.build_request(TOKEN, "acct_notreal")
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_the_account_header_selects_the_workspace(self):
        _url, headers = codex_usage.build_request(TOKEN, "acct_notreal")
        assert headers["ChatGPT-Account-Id"] == "acct_notreal"

    def test_an_unknown_account_sends_no_account_header(self):
        _url, headers = codex_usage.build_request(TOKEN, None)
        assert "ChatGPT-Account-Id" not in headers


class TestParsingAFullPayload:

    def test_both_windows_come_back_in_a_fixed_order(self):
        windows = codex_usage.parse_usage(FULL_PAYLOAD)
        assert [w.kind for w in windows] == ["primary", "secondary"]

    def test_used_percent_is_read_as_the_percent_used(self):
        windows = codex_usage.parse_usage(FULL_PAYLOAD)
        assert windows[0].used_pct == 42.0
        assert windows[1].used_pct == 7.5

    def test_the_window_length_is_taken_from_the_payload(self):
        windows = codex_usage.parse_usage(FULL_PAYLOAD)
        assert [w.window_seconds for w in windows] == [18000, 604800]

    def test_the_labels_are_derived_from_the_window_length(self):
        windows = codex_usage.parse_usage(FULL_PAYLOAD)
        assert [w.label for w in windows] == ["5h", "7d"]

    def test_the_epoch_reset_becomes_an_aware_datetime(self):
        window = codex_usage.parse_usage(FULL_PAYLOAD)[0]
        assert window.resets_at == datetime.fromtimestamp(1774020000, tz=timezone.utc)
        assert window.resets_at.tzinfo is not None

    def test_an_iso_reset_is_tolerated_too(self):
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 5,
                    "limit_window_seconds": 18000,
                    "reset_at": "2026-09-17T18:00:00Z",
                }
            }
        }
        window = codex_usage.parse_usage(payload)[0]
        assert window.resets_at == datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)


class TestTheWindowLabels:

    @pytest.mark.parametrize(
        "seconds,label",
        [
            (18000, "5h"),
            (3600, "1h"),
            (604800, "7d"),
            (86400, "1d"),
            (5400, "90m"),
            (129600, "2160m"),
        ],
    )
    def test_a_length_renders_as_hours_days_or_minutes(self, seconds, label):
        payload = {
            "rate_limit": {
                "primary_window": {"used_percent": 1, "limit_window_seconds": seconds}
            }
        }
        assert codex_usage.parse_usage(payload)[0].label == label

    def test_a_minutes_field_is_read_when_seconds_are_absent(self):
        payload = {
            "rate_limit": {"primary_window": {"used_percent": 1, "window_minutes": 300}}
        }
        window = codex_usage.parse_usage(payload)[0]
        assert window.window_seconds == 18000
        assert window.label == "5h"

    def test_an_unstated_length_labels_itself_rather_than_inventing_one(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": 1}}}
        window = codex_usage.parse_usage(payload)[0]
        assert window.window_seconds is None
        assert window.label == "primary"


class TestParsingPartialAndGarbagePayloads:

    def test_an_absent_secondary_window_is_simply_not_reported(self):
        payload = {"rate_limit": dict(FULL_PAYLOAD["rate_limit"])}
        payload["rate_limit"].pop("secondary_window")
        assert [w.kind for w in codex_usage.parse_usage(payload)] == ["primary"]

    def test_a_window_with_no_percentage_is_not_reported(self):
        payload = {"rate_limit": {"primary_window": {"limit_window_seconds": 18000}}}
        assert codex_usage.parse_usage(payload) == []

    def test_an_empty_object_reports_nothing(self):
        assert codex_usage.parse_usage({}) == []

    def test_a_rate_limit_that_is_not_an_object_does_not_raise(self):
        assert codex_usage.parse_usage({"rate_limit": "none"}) == []

    def test_a_window_that_is_not_an_object_does_not_raise(self):
        assert codex_usage.parse_usage({"rate_limit": {"primary_window": 42}}) == []

    def test_a_boolean_percentage_is_not_a_percentage(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": True}}}
        assert codex_usage.parse_usage(payload) == []


class TestTheStatusLadder:

    @pytest.mark.asyncio
    async def test_a_200_is_ok_and_carries_the_windows_and_the_plan(self):
        async with client_over(responder_for(200, FULL_PAYLOAD)) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "ok"
        assert [w.kind for w in outcome.windows] == ["primary", "secondary"]
        assert outcome.plan == "pro"
        assert outcome.error is None

    @pytest.mark.asyncio
    async def test_a_200_with_no_plan_type_names_no_plan(self):
        async with client_over(responder_for(200, {"rate_limit": {}})) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "ok"
        assert outcome.plan is None

    @pytest.mark.asyncio
    async def test_a_401_is_an_expired_credential(self):
        async with client_over(responder_for(401, {"detail": "nope"})) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "expired"
        assert outcome.windows == []

    @pytest.mark.asyncio
    async def test_a_403_is_refused_and_not_reported_as_expired(self):
        async with client_over(responder_for(403, text="<html>challenge</html>")) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "refused"

    @pytest.mark.asyncio
    async def test_a_429_with_a_retry_after_reports_the_seconds(self):
        responder = responder_for(429, {"detail": "slow"}, headers={"Retry-After": "30"})
        async with client_over(responder) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "rate_limited"
        assert outcome.retry_after_seconds == 30.0

    @pytest.mark.asyncio
    async def test_a_429_with_no_header_is_still_rate_limited(self):
        async with client_over(responder_for(429, {"detail": "slow"})) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "rate_limited"
        assert outcome.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_a_500_is_an_error_naming_the_status(self):
        async with client_over(responder_for(500, text="boom")) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "error"
        assert "500" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_a_timeout_is_an_error_rather_than_an_exception(self):

        def time_out(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        async with client_over(time_out) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "error"
        assert outcome.error == "timeout"

    @pytest.mark.asyncio
    async def test_a_connect_error_is_an_error_rather_than_an_exception(self):

        def refuse(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        async with client_over(refuse) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "error"
        assert outcome.error == "unreachable"

    @pytest.mark.asyncio
    async def test_a_200_that_is_not_json_is_an_error(self):
        async with client_over(responder_for(200, text="<html>hi</html>")) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "error"
        assert outcome.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_a_200_carrying_a_list_is_an_error(self):
        async with client_over(responder_for(200, json_body=[])) as client:
            outcome = await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert outcome.state == "error"


class TestTheTokenNeverReachesALog:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
    async def test_no_record_from_any_status_carries_the_token(self, status):
        async with client_over(responder_for(status, {"rate_limit": {}})) as client:
            with structlog.testing.capture_logs() as captured:
                await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert TOKEN not in repr(captured)

    @pytest.mark.asyncio
    async def test_no_record_from_a_transport_failure_carries_the_token(self):

        def refuse(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        async with client_over(refuse) as client:
            with structlog.testing.capture_logs() as captured:
                await codex_usage.fetch_usage(client, TOKEN, "acct_notreal")
        assert TOKEN not in repr(captured)
        assert captured, "the transport failure must log something at all"

    def test_reading_a_corrupt_id_token_never_logs_it(self):
        with structlog.testing.capture_logs() as captured:
            codex_usage.account_id_from_id_token(FULL_ID_TOKEN)
            codex_usage.account_id_from_id_token("header.!!!.sig")
        assert FULL_ID_TOKEN not in repr(captured)
