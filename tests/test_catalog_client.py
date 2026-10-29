
from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from src.core.catalog import client as catalog_client
from src.core.catalog.client import (
    INDEX_UNAVAILABLE,
    MAX_INDEX_BYTES,
    TLS_VERIFY_FAILED,
    FetchRefusal,
    IndexFetch,
    fetch_index,
    minisig_url,
)
from src.core.catalog.verify_types import INDEX_NOT_JSON
from tests.helpers.static_http import etag_for, self_signed_cert, serve_directory

INDEX_BODY = json.dumps(
    {"schema": "carnivore.catalog.index/1", "serial": 7, "items": []}
).encode("utf-8")

MINISIG_TEXT = (
    "untrusted comment: signature from minisign secret key\n"
    "RUQf6LRCGA9i53mfGBnxJ3YTIfMx4jT9nnhV5eqRzJBI1dLyBQqyTQ2k\n"
    "trusted comment: timestamp:1757894400\tfile:index.json\n"
    "kTnFLBBMHc1XLSt6nqXSy2SnCZBZoQ9LVCWhDNfPaG1CmsSGMDfDHOh1\n"
)


@pytest.fixture
def index_root(tmp_path: Path) -> Path:
    root = tmp_path / "served"
    (root / "v1").mkdir(parents=True)
    (root / "v1" / "index.json").write_bytes(INDEX_BODY)
    (root / "v1" / "index.json.minisig").write_text(MINISIG_TEXT)
    return root


@pytest.fixture
def trusted_tls(tmp_path: Path):
    cert = self_signed_cert(tmp_path)
    if cert is None:
        pytest.skip("cryptography is not importable, so no certificate can be made")
    return cert


@pytest_asyncio.fixture(autouse=True)
async def _closed_client():
    await catalog_client.shutdown()
    yield
    await catalog_client.shutdown()


async def _pin(cert, *, timeout: httpx.Timeout | None = None) -> None:
    await catalog_client.init(timeout=timeout, verify=str(cert[0]))




def test_default_timeout_is_ten_seconds_with_a_five_second_connect():
    assert catalog_client.DEFAULT_TIMEOUT.read == 10.0
    assert catalog_client.DEFAULT_TIMEOUT.connect == 5.0


def test_the_signature_url_is_the_index_url_plus_minisig():
    assert (
        minisig_url("https://catalog.carnivore.ai/v1/index.json")
        == "https://catalog.carnivore.ai/v1/index.json.minisig"
    )


def test_the_signature_url_survives_a_query_string():
    assert (
        minisig_url("https://h/v1/index.json?x=1") == "https://h/v1/index.json.minisig?x=1"
    )




@pytest.mark.asyncio
async def test_a_good_fetch_returns_the_bytes_the_signature_covers(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, IndexFetch)
    assert result.index_bytes == INDEX_BODY
    assert result.minisig_text == MINISIG_TEXT
    assert result.etag == etag_for(INDEX_BODY)
    assert result.not_modified is False


@pytest.mark.asyncio
async def test_an_etag_round_trips_to_a_304_and_skips_the_signature(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        url = f"{server.base_url}/v1/index.json"
        first = await fetch_index(url, etag=None)
        assert isinstance(first, IndexFetch)
        server.requests.clear()
        second = await fetch_index(url, etag=first.etag)
        paths = server.seen()

    assert isinstance(second, IndexFetch)
    assert second.not_modified is True
    assert second.index_bytes is None
    assert second.minisig_text is None
    assert second.etag == first.etag
    assert paths == ["/v1/index.json"]




@pytest.mark.asyncio
async def test_a_redirect_is_refused_rather_than_followed(index_root, trusted_tls):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.redirect_paths.add("/v1/index.json")
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)
        paths = server.seen()

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert result.detail == "redirect refused"
    assert paths == ["/v1/index.json"]


@pytest.mark.asyncio
async def test_a_404_and_a_500_are_unavailable_with_different_details(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        url = f"{server.base_url}/v1/index.json"
        missing = await fetch_index(f"{server.base_url}/v1/nope.json", etag=None)
        server.status_overrides["/v1/index.json"] = 500
        broken = await fetch_index(url, etag=None)

    assert isinstance(missing, FetchRefusal) and isinstance(broken, FetchRefusal)
    assert missing.code == broken.code == INDEX_UNAVAILABLE
    assert "404" in missing.detail
    assert "500" in broken.detail
    assert missing.detail != broken.detail


@pytest.mark.asyncio
async def test_a_missing_signature_refuses_the_whole_fetch(index_root, trusted_tls):
    await _pin(trusted_tls)
    (index_root / "v1" / "index.json.minisig").unlink()
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "minisig" in result.detail


@pytest.mark.asyncio
async def test_a_timeout_is_unavailable(index_root, trusted_tls):
    await _pin(trusted_tls, timeout=httpx.Timeout(0.3))
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.slow_paths.add("/v1/index.json")
        server.slow_seconds = 2.0
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "timed out" in result.detail


@pytest.mark.asyncio
async def test_a_refused_connection_is_unavailable_not_a_tls_failure():
    result = await fetch_index("https://127.0.0.1:1/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "could not connect" in result.detail




@pytest.mark.asyncio
async def test_a_non_https_url_is_refused_before_any_socket_opens(index_root):
    with serve_directory(index_root) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)
        paths = server.seen()

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "not https" in result.detail
    assert paths == []


@pytest.mark.asyncio
async def test_a_self_signed_certificate_is_a_tls_verify_failure(
    index_root, trusted_tls
):
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == TLS_VERIFY_FAILED
    assert "certifi" in result.detail




@pytest.mark.asyncio
async def test_a_body_over_the_cap_is_refused_mid_stream(index_root, trusted_tls):
    await _pin(trusted_tls)
    oversized = index_root / "v1" / "index.json"
    oversized.write_bytes(b"0" * (MAX_INDEX_BYTES + 1024))
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "cap" in result.detail


@pytest.mark.asyncio
async def test_a_small_gzip_that_decompresses_past_the_cap_is_refused(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    bomb = b"0" * (MAX_INDEX_BYTES + 1024)
    (index_root / "v1" / "index.json").write_bytes(bomb)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.gzip_paths.add("/v1/index.json")
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert len(gzip.compress(bomb)) < MAX_INDEX_BYTES
    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "decompressed past" in result.detail


@pytest.mark.asyncio
async def test_a_gzip_body_within_the_cap_is_read_correctly(index_root, trusted_tls):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.gzip_paths.add("/v1/index.json")
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, IndexFetch)
    assert result.index_bytes == INDEX_BODY




@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_index_not_json(index_root, trusted_tls):
    await _pin(trusted_tls)
    (index_root / "v1" / "index.json").write_bytes(b"<html>maintenance</html>")
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_NOT_JSON


@pytest.mark.asyncio
async def test_a_refusal_detail_never_carries_the_body(index_root, trusted_tls):
    await _pin(trusted_tls)
    secret = b'{"totp_secret": "ZZTOPSECRETVALUE"}x'
    (index_root / "v1" / "index.json").write_bytes(secret)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_NOT_JSON
    assert "ZZTOPSECRET" not in result.detail


@pytest.mark.asyncio
async def test_a_signature_without_four_lines_is_index_not_json(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    (index_root / "v1" / "index.json.minisig").write_text("one\ntwo\nthree\n")
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}/v1/index.json", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_NOT_JSON
    assert "3 lines" in result.detail




@pytest.mark.asyncio
async def test_init_and_shutdown_are_both_idempotent():
    await catalog_client.init()
    await catalog_client.init()

    assert catalog_client._client is not None
    assert not catalog_client._client.is_closed

    await catalog_client.shutdown()
    assert catalog_client._client is None
    await catalog_client.shutdown()
    assert catalog_client._client is None


@pytest.mark.asyncio
async def test_a_fetch_builds_the_client_without_an_explicit_init():
    assert catalog_client._client is None
    await fetch_index("https://127.0.0.1:1/v1/index.json", etag=None)
    assert catalog_client._client is not None
