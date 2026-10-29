
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import json

import httpx
import pytest
import structlog.testing

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cha_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cha_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog import hosted_api


def client_over(responder) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(responder), follow_redirects=False
    )


def patched(monkeypatch, responder) -> None:
    fake = client_over(responder)

    async def shared_client() -> httpx.AsyncClient:
        return fake

    monkeypatch.setattr(hosted_api, "shared_client", shared_client)


class TestTheUrlRules:

    def test_a_plain_http_base_is_refused(self):
        assert hosted_api.refuse_api_base_url("http://catalog.example/api/v1")

    def test_an_https_base_is_accepted(self):
        assert hosted_api.refuse_api_base_url("https://catalog.example/api/v1") is None

    def test_userinfo_is_refused_rather_than_stripped(self):
        assert hosted_api.refuse_api_base_url("https://u:p@catalog.example/api/v1")

    def test_an_unparseable_url_is_refused_rather_than_raising(self):
        assert hosted_api.refuse_api_base_url("https://catalog.example:99999/api/v1")

    def test_the_refusal_never_quotes_the_url(self):
        detail = hosted_api.refuse_api_base_url("https://u:secretpw@catalog.example/v1")
        assert detail is not None
        assert "secretpw" not in detail


class TestWhatComesBack:

    @pytest.mark.asyncio
    async def test_a_200_comes_back_as_its_status_and_its_body(self, monkeypatch):
        patched(
            monkeypatch,
            lambda request: httpx.Response(200, json={"count": 2, "average": 4.5}),
        )
        answer = await hosted_api.call(
            "https://catalog.example/api/v1", "GET", "/items/a/b/ratings"
        )
        assert answer.status == 200
        assert answer.body == {"count": 2, "average": 4.5}

    @pytest.mark.asyncio
    async def test_a_refusal_comes_back_as_a_value_not_an_exception(self, monkeypatch):
        patched(
            monkeypatch,
            lambda request: httpx.Response(
                404, json={"code": "unknown_item", "detail": "no such item"}
            ),
        )
        answer = await hosted_api.call(
            "https://catalog.example/api/v1", "GET", "/items/a/b/ratings"
        )
        assert answer.status == 404
        assert answer.body["code"] == "unknown_item"

    @pytest.mark.asyncio
    async def test_the_path_is_joined_onto_the_base_exactly_once(self, monkeypatch):
        seen = []
        patched(
            monkeypatch,
            lambda request: (seen.append(str(request.url)), httpx.Response(200, json={}))[1],
        )
        await hosted_api.call(
            "https://catalog.example/api/v1/", "GET", "/items/a/b/ratings"
        )
        assert seen == ["https://catalog.example/api/v1/items/a/b/ratings"]

    @pytest.mark.asyncio
    async def test_a_bearer_is_sent_only_when_one_was_given(self, monkeypatch):
        seen = []
        patched(
            monkeypatch,
            lambda request: (
                seen.append(request.headers.get("authorization")),
                httpx.Response(200, json={}),
            )[1],
        )
        await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")
        await hosted_api.call(
            "https://catalog.example/api/v1", "GET", "/x", bearer="tok"
        )
        assert seen == [None, "Bearer tok"]

    @pytest.mark.asyncio
    async def test_a_body_is_sent_as_json(self, monkeypatch):
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request.content)
            return httpx.Response(200, json={})

        patched(monkeypatch, respond)
        await hosted_api.call(
            "https://catalog.example/api/v1",
            "POST",
            "/auth/device/poll",
            json_body={"device_code": "abc"},
        )
        assert [json.loads(body) for body in seen] == [{"device_code": "abc"}]


class TestWhenItCannotBeReached:

    @pytest.mark.asyncio
    async def test_a_transport_failure_is_this_modules_own_refusal(self, monkeypatch):

        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        patched(monkeypatch, explode)
        with pytest.raises(hosted_api.HostedUnavailable) as caught:
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")
        assert caught.value.code == hosted_api.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_non_https_base_never_opens_a_socket(self, monkeypatch):
        reached = []

        async def shared_client():
            reached.append(True)
            raise AssertionError("the pool must not be reached for a refused url")

        monkeypatch.setattr(hosted_api, "shared_client", shared_client)
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("http://catalog.example/api/v1", "GET", "/x")
        assert reached == []

    @pytest.mark.asyncio
    async def test_something_that_is_not_json_is_refused(self, monkeypatch):
        patched(
            monkeypatch,
            lambda request: httpx.Response(200, text="<html>bad gateway</html>"),
        )
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")

    @pytest.mark.asyncio
    async def test_a_redirect_is_refused_rather_than_followed(self, monkeypatch):
        patched(
            monkeypatch,
            lambda request: httpx.Response(302, headers={"location": "https://elsewhere/"}),
        )
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")

    @pytest.mark.asyncio
    async def test_an_oversized_body_is_refused_mid_read(self, monkeypatch):
        huge = b'{"x":"' + b"y" * (hosted_api.MAX_HOSTED_BYTES + 32) + b'"}'
        patched(monkeypatch, lambda request: httpx.Response(200, content=huge))
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")


class _BreakingStream(httpx.AsyncByteStream):

    async def __aiter__(self):
        yield b'{"partial":'
        raise httpx.ReadError("connection reset while reading the body")


class TestTheOneRetry:

    @pytest.mark.asyncio
    async def test_a_read_that_died_before_answering_is_tried_once_more(
        self, monkeypatch
    ):
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            if len(seen) == 1:
                raise httpx.RemoteProtocolError(
                    "server disconnected without sending a response"
                )
            return httpx.Response(200, json={"count": 2, "average": 4.5})

        patched(monkeypatch, respond)
        answer = await hosted_api.call(
            "https://catalog.example/api/v1", "GET", "/items/a/b/ratings"
        )
        assert answer.status == 200
        assert answer.body == {"count": 2, "average": 4.5}
        assert seen == ["GET", "GET"]

    @pytest.mark.asyncio
    async def test_the_retry_is_bounded_at_two_attempts_and_still_refuses(
        self, monkeypatch
    ):
        seen = []

        def explode(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            raise httpx.RemoteProtocolError("server disconnected")

        patched(monkeypatch, explode)
        with pytest.raises(hosted_api.HostedUnavailable) as caught:
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")
        assert caught.value.code == hosted_api.UNAVAILABLE
        assert seen == ["GET", "GET"]
        assert len(seen) == hosted_api._MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_a_write_is_never_retried_however_it_failed(self, monkeypatch):
        seen = []

        def explode(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            raise httpx.RemoteProtocolError("server disconnected")

        patched(monkeypatch, explode)
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call(
                "https://catalog.example/api/v1",
                "POST",
                "/auth/device/poll",
                json_body={"device_code": "abc"},
            )
        assert seen == ["POST"]

    @pytest.mark.asyncio
    async def test_a_read_that_died_mid_body_is_not_retried(self, monkeypatch):
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_BreakingStream(),
            )

        patched(monkeypatch, respond)
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")
        assert seen == ["GET"]

    @pytest.mark.asyncio
    async def test_a_timeout_is_not_retried(self, monkeypatch):
        seen = []

        def stall(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            raise httpx.ReadTimeout("timed out")

        patched(monkeypatch, stall)
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/x")
        assert seen == ["GET"]

    @pytest.mark.asyncio
    async def test_the_failure_is_logged_once_and_carries_no_token(self, monkeypatch):
        token = "notarealtokenbutlongenoughtofind"

        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.RemoteProtocolError("server disconnected")

        patched(monkeypatch, explode)
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(hosted_api.HostedUnavailable):
                await hosted_api.call(
                    "https://catalog.example/api/v1",
                    "GET",
                    "/items/a/b/ratings",
                    bearer=token,
                )

        failures = [e for e in captured if e["event"] == "catalog_hosted_call_failed"]
        assert len(failures) == 1
        entry = failures[0]
        assert entry["method"] == "GET"
        assert entry["path"] == "/items/a/b/ratings"
        assert entry["error"] == "RemoteProtocolError"
        assert entry["attempts"] == 2
        assert isinstance(entry["elapsed_ms"], float)
        assert token not in repr(captured)
