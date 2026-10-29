
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import structlog.testing

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.provider_ledger import claude_usage

TOKEN = "sk-ant-oat01-notarealtokenbutlongenoughtofind"

FULL_PAYLOAD = {
    "five_hour": {"utilization": 42, "resets_at": "2026-09-17T18:00:00Z"},
    "seven_day": {"utilization": 15, "resets_at": "2026-09-22T00:00:00Z"},
    "seven_day_opus": {"utilization": 61, "resets_at": "2026-09-22T06:00:00Z"},
    "seven_day_sonnet": {"utilization": 8.5, "resets_at": "2026-09-22T12:00:00Z"},
    "seven_day_routines": {"utilization": 3, "resets_at": "2026-09-22T00:00:00Z"},
    "extra_usage": {"is_enabled": True, "monthly_limit": 5000, "used_credits": 1234},
    "spend": {},
    "member_dashboard_available": False,
}


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


class TestTheRequest:

    def test_the_url_is_the_oauth_usage_endpoint(self):
        url, _headers = claude_usage.build_request(TOKEN)
        assert url == "https://api.anthropic.com/api/oauth/usage"

    def test_the_token_rides_as_a_bearer(self):
        _url, headers = claude_usage.build_request(TOKEN)
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_the_oauth_beta_header_is_sent(self):
        _url, headers = claude_usage.build_request(TOKEN)
        assert headers["anthropic-beta"] == "oauth-2025-04-20"


class TestParsingAFullPayload:

    def test_the_four_named_windows_come_back_in_a_fixed_order(self):
        windows = claude_usage.parse_usage(FULL_PAYLOAD)
        assert [w.kind for w in windows] == [
            "five_hour",
            "seven_day",
            "seven_day_opus",
            "seven_day_sonnet",
        ]

    def test_utilization_is_read_as_the_percent_used(self):
        windows = claude_usage.parse_usage(FULL_PAYLOAD)
        assert windows[0].used_pct == 42.0
        assert windows[3].used_pct == 8.5

    def test_each_window_carries_its_length_in_seconds(self):
        windows = claude_usage.parse_usage(FULL_PAYLOAD)
        assert windows[0].window_seconds == 18000
        assert [w.window_seconds for w in windows[1:]] == [604800, 604800, 604800]

    def test_the_labels_are_the_human_windows(self):
        windows = claude_usage.parse_usage(FULL_PAYLOAD)
        assert [w.label for w in windows] == ["5h", "7d", "7d opus", "7d sonnet"]

    def test_resets_at_becomes_an_aware_datetime(self):
        window = claude_usage.parse_usage(FULL_PAYLOAD)[0]
        assert window.resets_at == datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)
        assert window.resets_at.tzinfo is not None

    def test_an_unrecognised_window_key_is_not_reported(self):
        kinds = {w.kind for w in claude_usage.parse_usage(FULL_PAYLOAD)}
        assert "seven_day_routines" not in kinds


class TestParsingAPartialPayload:

    def test_an_absent_window_is_simply_not_reported(self):
        windows = claude_usage.parse_usage({"five_hour": FULL_PAYLOAD["five_hour"]})
        assert [w.kind for w in windows] == ["five_hour"]

    def test_a_null_window_is_not_reported(self):
        payload = dict(FULL_PAYLOAD, seven_day_opus=None, seven_day_sonnet=None)
        kinds = [w.kind for w in claude_usage.parse_usage(payload)]
        assert kinds == ["five_hour", "seven_day"]

    def test_a_window_with_no_utilization_is_not_reported(self):
        windows = claude_usage.parse_usage({"five_hour": {"resets_at": None}})
        assert windows == []

    def test_a_window_with_no_reset_still_reports_its_percentage(self):
        windows = claude_usage.parse_usage({"five_hour": {"utilization": 12}})
        assert len(windows) == 1
        assert windows[0].used_pct == 12.0
        assert windows[0].resets_at is None


class TestParsingGarbage:

    def test_an_empty_object_reports_nothing(self):
        assert claude_usage.parse_usage({}) == []

    def test_a_string_where_a_window_belongs_does_not_raise(self):
        assert claude_usage.parse_usage({"five_hour": "42%"}) == []

    def test_a_boolean_utilization_is_not_a_percentage(self):
        assert claude_usage.parse_usage({"five_hour": {"utilization": True}}) == []

    def test_a_non_numeric_utilization_does_not_raise(self):
        assert claude_usage.parse_usage({"five_hour": {"utilization": "42"}}) == []


class TestTheResetStampForms:

    def test_epoch_seconds_are_read_as_seconds(self):
        payload = {"five_hour": {"utilization": 1, "resets_at": 1774020000}}
        window = claude_usage.parse_usage(payload)[0]
        assert window.resets_at == datetime.fromtimestamp(1774020000, tz=timezone.utc)

    def test_epoch_milliseconds_are_read_as_milliseconds(self):
        payload = {"five_hour": {"utilization": 1, "resets_at": 1774020000000}}
        window = claude_usage.parse_usage(payload)[0]
        assert window.resets_at == datetime.fromtimestamp(1774020000, tz=timezone.utc)

    def test_a_quoted_number_is_still_a_stamp(self):
        payload = {"five_hour": {"utilization": 1, "resets_at": "1774020000"}}
        window = claude_usage.parse_usage(payload)[0]
        assert window.resets_at == datetime.fromtimestamp(1774020000, tz=timezone.utc)

    def test_an_iso_stamp_with_an_offset_keeps_its_instant(self):
        payload = {
            "five_hour": {"utilization": 1, "resets_at": "2026-09-17T14:00:00-04:00"}
        }
        window = claude_usage.parse_usage(payload)[0]
        assert window.resets_at == datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)

    def test_an_unreadable_stamp_is_none_rather_than_now(self):
        payload = {"five_hour": {"utilization": 1, "resets_at": "soon"}}
        assert claude_usage.parse_usage(payload)[0].resets_at is None


class TestTheStatusLadder:

    @pytest.mark.asyncio
    async def test_a_200_is_ok_and_carries_the_windows(self):
        async with client_over(responder_for(200, FULL_PAYLOAD)) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "ok"
        assert [w.kind for w in outcome.windows] == [
            "five_hour",
            "seven_day",
            "seven_day_opus",
            "seven_day_sonnet",
        ]
        assert outcome.error is None

    @pytest.mark.asyncio
    async def test_a_401_is_an_expired_credential(self):
        async with client_over(responder_for(401, {"error": "unauthorized"})) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "expired"
        assert outcome.windows == []

    @pytest.mark.asyncio
    async def test_a_403_naming_the_scope_says_which_scope_is_missing(self):
        body = {"error": {"message": "requires the user:profile scope"}}
        async with client_over(responder_for(403, body)) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "refused"
        assert "user:profile" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_any_other_403_is_refused_without_naming_a_scope(self):
        async with client_over(responder_for(403, text="nope")) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "refused"
        assert "user:profile" not in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_a_429_with_a_retry_after_reports_the_seconds(self):
        responder = responder_for(429, {"error": "slow down"}, headers={"Retry-After": "120"})
        async with client_over(responder) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "rate_limited"
        assert outcome.retry_after_seconds == 120.0

    @pytest.mark.asyncio
    async def test_a_429_with_retry_after_zero_is_still_rate_limited(self):
        responder = responder_for(429, {"error": "slow down"}, headers={"Retry-After": "0"})
        async with client_over(responder) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "rate_limited"
        assert outcome.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_a_429_with_no_header_is_still_rate_limited(self):
        async with client_over(responder_for(429, {"error": "slow down"})) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "rate_limited"
        assert outcome.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_a_500_is_an_error_naming_the_status(self):
        async with client_over(responder_for(500, text="boom")) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "error"
        assert "500" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_a_timeout_is_an_error_rather_than_an_exception(self):

        def time_out(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        async with client_over(time_out) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "error"
        assert outcome.error == "timeout"

    @pytest.mark.asyncio
    async def test_a_connect_error_is_an_error_rather_than_an_exception(self):

        def refuse(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        async with client_over(refuse) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "error"
        assert outcome.error == "unreachable"

    @pytest.mark.asyncio
    async def test_a_200_that_is_not_json_is_an_error(self):
        async with client_over(responder_for(200, text="<html>hi</html>")) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "error"
        assert outcome.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_a_200_carrying_a_list_is_an_error(self):
        async with client_over(responder_for(200, json_body=[])) as client:
            outcome = await claude_usage.fetch_usage(client, TOKEN)
        assert outcome.state == "error"


class TestTheTokenNeverReachesALog:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
    async def test_no_record_from_any_status_carries_the_token(self, status):
        async with client_over(responder_for(status, {"five_hour": None})) as client:
            with structlog.testing.capture_logs() as captured:
                await claude_usage.fetch_usage(client, TOKEN)
        assert TOKEN not in repr(captured)

    @pytest.mark.asyncio
    async def test_no_record_from_a_transport_failure_carries_the_token(self):

        def refuse(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        async with client_over(refuse) as client:
            with structlog.testing.capture_logs() as captured:
                await claude_usage.fetch_usage(client, TOKEN)
        assert TOKEN not in repr(captured)
        assert captured, "the transport failure must log something at all"
