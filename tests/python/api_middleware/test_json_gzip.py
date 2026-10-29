
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

from src.api.json_gzip import MIN_BYTES, JsonGzipMiddleware

BIG = {"rows": ["x" * 100] * (MIN_BYTES // 50)}


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(JsonGzipMiddleware)
    app.get("/big")(lambda: BIG)
    app.get("/small")(lambda: {"ok": True})
    app.get("/text")(lambda: PlainTextResponse("y" * (MIN_BYTES * 2)))
    app.get("/stream")(lambda: StreamingResponse(iter([b"data: 1\n\n"] * 3), media_type="text/event-stream"))
    return TestClient(app)


def test_large_json_is_gzipped_when_accepted_and_round_trips():
    raw = make_client().get("/big", headers={"Accept-Encoding": "gzip"})
    assert raw.headers["content-encoding"] == "gzip" and "Accept-Encoding" in raw.headers["vary"]
    assert raw.json() == BIG
    assert int(raw.headers["content-length"]) < len(json.dumps(BIG)) // 5


def test_wire_bytes_are_a_valid_gzip_stream():
    with make_client().stream("GET", "/big", headers={"Accept-Encoding": "gzip"}) as response:
        wire = b"".join(response.iter_raw())
    assert json.loads(gzip.decompress(wire)) == BIG


def test_no_gzip_without_accept_encoding_small_bodies_text_or_streams():
    client = make_client()
    assert "content-encoding" not in client.get("/big", headers={"Accept-Encoding": "identity"}).headers
    assert "content-encoding" not in client.get("/small", headers={"Accept-Encoding": "gzip"}).headers
    assert "content-encoding" not in client.get("/text", headers={"Accept-Encoding": "gzip"}).headers
    stream = client.get("/stream", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in stream.headers and stream.text == "data: 1\n\n" * 3
