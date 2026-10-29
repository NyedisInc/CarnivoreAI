
import asyncio
import functools
import json

import httpx
import pytest

from src.core.byoai import transport
from src.core.byoai.contracts import ByoaiError, Connection, ProviderHTTPError, ProviderTimeout, Target
from src.core.byoai.media import fal

SECRET = "q" * 20 + "FAL9"
HOST = "https://queue.fal.run"


def sync(fn):
    @functools.wraps(fn)
    def run(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return run


def _conn(**options) -> Connection:
    return Connection(id="fal1", preset="fal", base_url=HOST, key_host="https://queue.fal.run",
                      options=dict(options))


def _install(monkeypatch, handler, seen):
    real = httpx.AsyncClient

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        return handler(request)

    monkeypatch.setattr(transport.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw))
    monkeypatch.setattr(fal, "POLL_START_S", 0.001)


def _queue(statuses, result=None, result_status=200, status_url=None):
    polls = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            assert json.loads(request.content)["prompt"] == "a cat"
            return httpx.Response(200, json={
                "request_id": "r1",
                "status_url": status_url or f"{HOST}/fal-ai/flux/requests/r1/status",
                "response_url": f"{HOST}/fal-ai/flux/requests/r1",
                "cancel_url": f"{HOST}/fal-ai/flux/requests/r1/cancel"})
        if request.method == "PUT":
            return httpx.Response(200, json={})
        if path.endswith("/status"):
            return httpx.Response(200, json=next(polls, {"status": "IN_PROGRESS"}))
        return httpx.Response(result_status, json=result)

    return handler


@sync
async def test_success_maps_images_and_sends_key_header(monkeypatch):
    seen = []
    body = {"images": [{"url": "https://v3.fal.media/a.png", "width": 512, "height": 512,
                        "content_type": "image/png"}], "seed": 7}
    _install(monkeypatch, _queue([{"status": "IN_QUEUE"}, {"status": "IN_PROGRESS"},
                                  {"status": "COMPLETED"}], body), seen)
    out = await fal.generate(Target(_conn(), "fal-ai/flux/schnell"), SECRET, "a cat", {"image_size": "square"})
    assert out.items[0].url == "https://v3.fal.media/a.png"
    assert (out.items[0].width, out.items[0].mime) == (512, "image/png")
    assert out.raw["seed"] == 7
    assert [p for _, p, _ in seen if p.endswith("/status")] == ["/fal-ai/flux/requests/r1/status"] * 3
    assert all(auth == f"Key {SECRET}" for _, _, auth in seen)


def test_video_and_audio_shapes_map():
    video = fal.map_items({"video": {"url": "https://x/v.mp4", "width": 1280, "height": 720, "duration": 5}})
    audio = fal.map_items({"audio_file": {"url": "https://x/a.wav", "content_type": "audio/wav"}})
    assert (video[0].mime, video[0].duration_s, video[0].height) == ("video/mp4", 5.0, 720)
    assert audio[0].mime == "audio/wav"


@sync
async def test_failed_job_raises_without_the_key(monkeypatch):
    _install(monkeypatch, _queue([{"status": "FAILED", "error": f"bad input {SECRET}"}]), [])
    with pytest.raises(ByoaiError) as err:
        await fal.generate(Target(_conn(), "fal-ai/flux/schnell"), SECRET, "a cat", {})
    assert "failed" in str(err.value) and SECRET not in str(err.value)


@sync
async def test_completed_then_error_result_hides_the_key(monkeypatch):
    _install(monkeypatch, _queue([{"status": "COMPLETED"}], {"detail": f"echo {SECRET}"}, 422), [])
    with pytest.raises(ProviderHTTPError) as err:
        await fal.generate(Target(_conn(), "fal-ai/flux/schnell"), SECRET, "a cat", {})
    assert err.value.status == 422 and SECRET not in err.value.body and SECRET not in str(err.value)


@sync
async def test_timeout_cancels_and_raises_without_the_key(monkeypatch):
    seen = []
    _install(monkeypatch, _queue([]), seen)
    with pytest.raises(ProviderTimeout) as err:
        await fal.generate(Target(_conn(timeout_s=0.05), "fal-ai/flux/schnell"), SECRET, "a cat", {})
    assert SECRET not in str(err.value)
    assert any(m == "PUT" and p.endswith("/cancel") for m, p, _ in seen)


@sync
async def test_foreign_status_host_is_refused(monkeypatch):
    seen = []
    _install(monkeypatch, _queue([], status_url="https://evil.example/s"), seen)
    with pytest.raises(ByoaiError) as err:
        await fal.generate(Target(_conn(), "fal-ai/flux/schnell"), SECRET, "a cat", {})
    assert SECRET not in str(err.value)
    assert all(p != "/s" for _, p, _ in seen)
