
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_spec_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_spec_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.spectator_links_store import (
    PURGE_GRACE_SECONDS,
    SpectatorLinksStore,
    hash_token,
)

SESSION = "ses_spectate_probe"


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "cloude.db")


async def _open(db_file) -> SpectatorLinksStore:
    store = SpectatorLinksStore(db_file)
    await store.init()
    return store


@pytest.mark.asyncio
async def test_the_raw_token_is_not_in_the_database(db_file):
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600, "demo")
    finally:
        await store.close()

    blob = Path(db_file).read_bytes()
    assert minted.token.encode("utf-8") not in blob, (
        "THE RAW TOKEN IS ON DISK. A stolen copy of cloude.db is then a "
        "set of working links into live terminals, not a list of shares."
    )
    assert hash_token(minted.token).encode("ascii") in blob, (
        "the hash is not in the file either, so this test would pass "
        "against a store that saved nothing at all"
    )


@pytest.mark.asyncio
async def test_each_link_is_declared_under_its_own_tokens_digest(db_file):
    store = await _open(db_file)
    try:
        first = await store.mint(SESSION, 600)
        second = await store.mint("ses_other", 600)

        declared = {lid: (sid, digest)
                    for lid, sid, digest, _nonce, _exp, _key in await store.live_relay_declarations()}
        assert declared[first.link.id] == (SESSION, hash_token(first.token))
        assert declared[second.link.id] == ("ses_other", hash_token(second.token))
        assert hash_token("not-a-token") not in {d for _, d in declared.values()}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_an_expired_link_is_kept_and_not_live(db_file):
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, -1)
        found = await store.get(minted.link.id)
        assert found is not None, "an expired link became unreadable"
        assert not found.is_live(), "an expired link reported itself live"

        live = await store.mint(SESSION, 600)
        assert (await store.get(live.link.id)).is_live(), (
            "no link reads as live, so the assertion above proves nothing"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_revoke_is_permanent_and_idempotent(db_file, monkeypatch):
    store_mod = sys.modules["src.core.spectator_links_store"]
    clock = {"now": 1_700_000_000.0}
    monkeypatch.setattr(store_mod, "time", SimpleNamespace(time=lambda: clock["now"]))

    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600)
        first = await store.revoke(minted.link.id)
        assert first is not None and first.revoked_at is not None
        assert not first.is_live(), "a revoked link still reported live"

        clock["now"] += 60
        again = await store.revoke(minted.link.id)
        assert again is not None
        assert again.revoked_at == first.revoked_at, (
            "a second revoke moved the timestamp, so the record of when "
            "the owner actually revoked it is lost"
        )
        assert (await store.revoke("no-such-link")) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_the_owners_list_shows_live_links_only(db_file):
    store = await _open(db_file)
    try:
        expired = await store.mint(SESSION, -1)
        revoked = await store.mint(SESSION, 600)
        await store.revoke(revoked.link.id)
        live = await store.mint(SESSION, 600)
        await store.mint("ses_other", 600)

        ids = [link.id for link in await store.list_for_session(SESSION)]
        assert ids == [live.link.id], f"the list is not live-only: {ids!r}"

        all_ids = {
            link.id
            for link in await store.list_for_session(SESSION, include_dead=True)
        }
        assert all_ids == {live.link.id, expired.link.id, revoked.link.id}, (
            f"a dead row was deleted rather than hidden: {all_ids!r}"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_purge_takes_the_long_dead_and_leaves_the_rest(db_file):
    store = await _open(db_file)
    try:
        now = int(time.time())
        live = await store.mint(SESSION, 600)
        recent = await store.mint(SESSION, -60)
        ancient = await store.mint(SESSION, -(PURGE_GRACE_SECONDS + 3600))

        deleted = await store.purge_expired()
        assert deleted == 1, f"purge deleted {deleted} rows, expected 1"
        assert (await store.get(ancient.link.id)) is None
        assert (await store.get(recent.link.id)) is not None, (
            "a link that expired a minute ago was deleted, so nothing can "
            "explain to its holder why it stopped working"
        )
        assert (await store.get(live.link.id)) is not None
        assert live.link.expires_at > now
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_a_second_init_on_the_same_file_keeps_the_rows(db_file):
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600)
    finally:
        await store.close()

    again = await _open(db_file)
    try:
        found = await again.get(minted.link.id)
        assert found is not None and found.id == minted.link.id, (
            "the rows did not survive a restart of the store"
        )
    finally:
        await again.close()


@pytest.mark.asyncio
async def test_a_second_mint_replaces_the_sessions_live_link(db_file):
    store = await _open(db_file)
    try:
        first = await store.mint(SESSION, 600)
        second = await store.mint(SESSION, 600)

        assert second.replaced == (first.link.id,), (
            "the mint did not report which link it displaced: "
            f"{second.replaced!r}"
        )
        assert first.replaced == (), "the first mint replaced something"

        live = [link.id for link in await store.list_for_session(SESSION)]
        assert live == [second.link.id], (
            f"the session has more than one live link: {live!r}"
        )

        displaced = await store.get(first.link.id)
        assert displaced is not None, "the replaced row was deleted, not revoked"
        assert displaced.revoked_at is not None and not displaced.is_live()
        stored = {
            link.id
            for link in await store.list_for_session(SESSION, include_dead=True)
        }
        assert stored == {first.link.id, second.link.id}, (
            f"the replaced row is not stored any more: {stored!r}"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_a_mint_replaces_only_its_own_sessions_link(db_file):
    store = await _open(db_file)
    try:
        neighbour = await store.mint("ses_neighbour", 600)
        mine = await store.mint(SESSION, 600)
        replacement = await store.mint(SESSION, 600)

        assert replacement.replaced == (mine.link.id,), (
            f"the same-session link was not replaced: {replacement.replaced!r}"
        )
        surviving = await store.get(neighbour.link.id)
        assert surviving is not None and surviving.revoked_at is None, (
            "a mint on one session revoked another session's live link"
        )
        assert surviving.is_live()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_live_expiry_by_session_answers_live_rows_only(db_file):
    store = await _open(db_file)
    try:
        live = await store.mint(SESSION, 600)
        await store.mint("ses_expired", -1)
        revoked = await store.mint("ses_revoked", 600)
        await store.revoke(revoked.link.id)

        expiry = await store.live_expiry_by_session()
        assert expiry == {SESSION: live.link.expires_at}, (
            f"a dead link reads as a live share: {expiry!r}"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_a_v2_mint_keeps_its_derived_id_and_nonce_and_an_old_table_gains_the_column(db_file):
    import sqlite3

    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE spectator_links (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
        "token_sha256 TEXT NOT NULL UNIQUE, label TEXT, created_at INTEGER NOT NULL, "
        "expires_at INTEGER NOT NULL, revoked_at INTEGER, last_connected_at INTEGER, "
        "connect_count INTEGER NOT NULL DEFAULT 0)")
    conn.execute("INSERT INTO spectator_links (id, session_id, token_sha256, created_at, "
                 "expires_at) VALUES ('old', 'ses_old', 'd', 1, ?)", (int(time.time()) + 600,))
    conn.commit()
    conn.close()
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600, identity=("derivedLinkId0000000000", "bm9uY2U"))
        declared = await store.live_relay_declarations()
        rows = {lid: nonce for lid, _s, _d, nonce, _e, _k in declared}
        keys = {lid: key for lid, _s, _d, _n, _e, key in declared}
        assert minted.link.id == "derivedLinkId0000000000"
        assert rows == {"old": None, "derivedLinkId0000000000": "bm9uY2U"}
        assert keys["old"] is None and len(keys["derivedLinkId0000000000"]) == 32
        assert minted.link.e2ee
    finally:
        await store.close()
    reopened = await _open(db_file)
    await reopened.close()



from src.core.spectator_links_store import (  # noqa: E402
    LINK_TOKEN_DB_FILENAME,
    link_token_db_path,
)


def _sidecar_blob(db_file) -> bytes:
    return link_token_db_path(db_file).read_bytes()


@pytest.mark.asyncio
async def test_a_live_links_token_is_kept_in_a_0600_sidecar_not_in_cloude_db(db_file):
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600, "demo")
        assert await store.live_token(minted.link.id) == minted.token
    finally:
        await store.close()

    sidecar = link_token_db_path(db_file)
    assert sidecar.name == LINK_TOKEN_DB_FILENAME
    assert sidecar.parent == Path(db_file).parent
    assert (sidecar.stat().st_mode & 0o777) == 0o600
    assert minted.token.encode("utf-8") in _sidecar_blob(db_file)
    blob = Path(db_file).read_bytes()
    assert minted.token.encode("utf-8") not in blob
    assert hash_token(minted.token).encode("ascii") in blob


@pytest.mark.asyncio
async def test_revoking_deletes_the_token_from_the_sidecar_file(db_file):
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600)
        assert minted.token.encode("utf-8") in _sidecar_blob(db_file)
        await store.revoke(minted.link.id)
        assert await store.live_token(minted.link.id) is None
    finally:
        await store.close()
    assert minted.token.encode("utf-8") not in _sidecar_blob(db_file)


@pytest.mark.asyncio
async def test_replacing_deletes_the_old_token_and_keeps_the_new(db_file):
    store = await _open(db_file)
    try:
        first = await store.mint(SESSION, 600)
        second = await store.mint(SESSION, 600)
        assert second.replaced == (first.link.id,)
        assert await store.live_token(first.link.id) is None
        assert await store.live_token(second.link.id) == second.token
    finally:
        await store.close()
    blob = _sidecar_blob(db_file)
    assert first.token.encode("utf-8") not in blob
    assert second.token.encode("utf-8") in blob


@pytest.mark.asyncio
async def test_an_expired_links_token_is_swept_from_the_sidecar(db_file, monkeypatch):
    store_mod = sys.modules["src.core.spectator_links_store"]
    clock = {"now": 1_700_000_000.0}
    monkeypatch.setattr(store_mod, "time", SimpleNamespace(time=lambda: clock["now"]))
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 60)
        assert minted.token.encode("utf-8") in _sidecar_blob(db_file)
        clock["now"] += 61
        await store.live_relay_declarations()
        assert minted.token.encode("utf-8") not in _sidecar_blob(db_file)
        assert await store.live_token(minted.link.id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_an_unreadable_sidecar_never_stops_the_store(db_file):
    link_token_db_path(db_file).write_bytes(b"not a sqlite database at all" * 64)
    store = await _open(db_file)
    try:
        minted = await store.mint(SESSION, 600)
        assert await store.get(minted.link.id) is not None
        assert await store.live_token(minted.link.id) is None
    finally:
        await store.close()
