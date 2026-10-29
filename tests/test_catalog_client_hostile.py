
from __future__ import annotations

import asyncio

import httpx
import pytest

from src.core.catalog import client as catalog_client
from src.core.catalog.client import (
    INDEX_UNAVAILABLE,
    FetchRefusal,
    IndexFetch,
    fetch_index,
)
from src.core.catalog.fetch_stream import fetch_document
from tests.helpers.static_http import serve_directory
from tests.test_catalog_client import (  # noqa: F401
    INDEX_BODY,
    _closed_client,
    _pin,
    index_root,
    trusted_tls,
)

ATTACKER_ETAG = '"attacker-chose-this"'

NON_ASCII_ETAG = '"café"'

INDEX_PATH = "/v1/index.json"




@pytest.mark.asyncio
async def test_a_304_to_an_unconditional_fetch_is_refused(index_root, trusted_tls):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.always_304_paths.add(INDEX_PATH)
        server.etag_overrides[INDEX_PATH] = ATTACKER_ETAG
        result = await fetch_index(f"{server.base_url}{INDEX_PATH}", etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "304 without a conditional request" in result.detail


@pytest.mark.asyncio
async def test_a_legitimate_304_returns_the_tag_we_sent_not_the_one_we_got(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        url = f"{server.base_url}{INDEX_PATH}"
        first = await fetch_index(url, etag=None)
        assert isinstance(first, IndexFetch)
        server.always_304_paths.add(INDEX_PATH)
        server.etag_overrides[INDEX_PATH] = ATTACKER_ETAG
        second = await fetch_index(url, etag=first.etag)

    assert isinstance(second, IndexFetch)
    assert second.not_modified is True
    assert second.etag == first.etag
    assert second.etag != ATTACKER_ETAG




@pytest.mark.asyncio
async def test_a_non_ascii_etag_is_not_stored_and_the_next_fetch_is_unconditional(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        url = f"{server.base_url}{INDEX_PATH}"
        server.etag_overrides[INDEX_PATH] = NON_ASCII_ETAG
        first = await fetch_index(url, etag=None)
        assert isinstance(first, IndexFetch)
        assert first.index_bytes == INDEX_BODY
        second = await fetch_index(url, etag=first.etag)

    assert first.etag is None
    assert isinstance(second, IndexFetch)
    assert second.index_bytes == INDEX_BODY


@pytest.mark.asyncio
async def test_a_weak_etag_is_kept_and_still_round_trips_to_a_304(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        url = f"{server.base_url}{INDEX_PATH}"
        server.etag_overrides[INDEX_PATH] = 'W/"abc123"'
        first = await fetch_index(url, etag=None)
        assert isinstance(first, IndexFetch)
        second = await fetch_index(url, etag=first.etag)

    assert first.etag == 'W/"abc123"'
    assert isinstance(second, IndexFetch)
    assert second.not_modified is True




@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://[::1/v1/index.json",
        "https://127.0.0.1:99999/v1/index.json",
    ],
)
async def test_a_malformed_index_url_is_refused_rather_than_raising(url):
    result = await fetch_index(url, etag=None)

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "could not be parsed" in result.detail


@pytest.mark.asyncio
async def test_a_url_carrying_userinfo_is_refused_before_any_socket(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        authority = server.base_url.split("://", 1)[1]
        result = await fetch_index(
            f"https://catalog:hunter2@{authority}{INDEX_PATH}", etag=None
        )
        paths = server.seen()

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "userinfo in url" in result.detail
    assert "hunter2" not in result.detail
    assert paths == []




@pytest.mark.asyncio
async def test_a_document_fetch_refuses_an_invalid_url(index_root):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        result = await fetch_document(
            client, "https://[::1/x", limit=1024, url_kind="index"
        )

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_document_fetch_refuses_an_out_of_range_port():
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=httpx.Timeout(2.0)
    ) as client:
        result = await fetch_document(
            client, "https://127.0.0.1:99999/x", limit=1024, url_kind="index"
        )

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_document_fetch_refuses_a_header_it_cannot_encode():
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=httpx.Timeout(2.0)
    ) as client:
        result = await fetch_document(
            client,
            "https://127.0.0.1:1/x",
            limit=1024,
            url_kind="index",
            extra_headers={"If-None-Match": NON_ASCII_ETAG},
        )

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_document_fetch_refuses_a_client_that_is_already_closed():
    client = httpx.AsyncClient(follow_redirects=False)
    await client.aclose()

    result = await fetch_document(
        client, "https://127.0.0.1:1/x", limit=1024, url_kind="index"
    )

    assert isinstance(result, FetchRefusal)
    assert result.code == INDEX_UNAVAILABLE
    assert "closed" in result.detail




@pytest.mark.asyncio
async def test_init_twice_with_the_same_options_keeps_the_live_client():
    await catalog_client.init()
    first = catalog_client._client
    await catalog_client.init()

    assert catalog_client._client is first
    assert first is not None and not first.is_closed


@pytest.mark.asyncio
async def test_init_with_different_options_replaces_and_closes_the_old_client():
    await catalog_client.init()
    first = catalog_client._client
    await catalog_client.init(timeout=httpx.Timeout(1.0))
    second = catalog_client._client

    assert second is not first
    assert first is not None and first.is_closed
    assert second is not None and not second.is_closed


@pytest.mark.asyncio
async def test_a_fetch_rebuilds_a_client_that_was_closed_underneath_it(
    index_root, trusted_tls
):
    await _pin(trusted_tls)
    stale = catalog_client._client
    assert stale is not None
    await stale.aclose()

    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        result = await fetch_index(f"{server.base_url}{INDEX_PATH}", etag=None)

    assert isinstance(result, IndexFetch)
    assert result.index_bytes == INDEX_BODY
    assert catalog_client._client is not stale


@pytest.mark.asyncio
async def test_shutdown_waits_for_a_fetch_that_is_still_running(
    index_root, trusted_tls
):
    await _pin(trusted_tls, timeout=httpx.Timeout(10.0))
    with serve_directory(index_root, tls_cert=trusted_tls) as server:
        server.slow_paths.add(INDEX_PATH)
        server.slow_seconds = 0.75
        running = asyncio.create_task(
            fetch_index(f"{server.base_url}{INDEX_PATH}", etag=None)
        )
        await asyncio.sleep(0.2)
        await catalog_client.shutdown()
        result = await running

    assert isinstance(result, IndexFetch)
    assert result.index_bytes == INDEX_BODY
