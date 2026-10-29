
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_speclist_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_speclist_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.spectator_listing import iso_utc, mark_shared
from src.core.spectator_links_store import SpectatorLinksStore
from src.models import Session, SessionInfo

SHARED = "ses_shared_probe"
PRIVATE = "ses_private_probe"


def _infos(*session_ids):
    return [
        SessionInfo(session=Session(id=session_id, working_dir="/tmp"))
        for session_id in session_ids
    ]


async def _open(db_file) -> SpectatorLinksStore:
    store = SpectatorLinksStore(str(db_file))
    await store.init()
    return store


@pytest.mark.asyncio
async def test_only_the_shared_session_carries_an_expiry(tmp_path):
    store = await _open(tmp_path / "cloude.db")
    try:
        minted = await store.mint(SHARED, 600)
        infos = _infos(SHARED, PRIVATE)
        assert len(infos) == 2, "nothing was listed, so nothing below is tested"

        await mark_shared(SimpleNamespace(spectator_links=store), infos)

        by_id = {info.session.id: info.spectator_expires_at for info in infos}
        assert by_id[SHARED] == iso_utc(minted.link.expires_at), (
            f"the shared session's deadline is wrong: {by_id[SHARED]!r}"
        )
        assert by_id[SHARED] is not None and "T" in by_id[SHARED], (
            "the deadline did not render as ISO 8601"
        )
        assert by_id[PRIVATE] is None, (
            "a session with no share was marked as shared: "
            f"{by_id[PRIVATE]!r}"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_a_revoked_share_stops_marking_its_session(tmp_path):
    store = await _open(tmp_path / "cloude.db")
    try:
        minted = await store.mint(SHARED, 600)
        app_state = SimpleNamespace(spectator_links=store)

        infos = _infos(SHARED)
        assert len(infos) == 1, "nothing was listed, so nothing below is tested"
        await mark_shared(app_state, infos)
        assert infos[0].spectator_expires_at is not None, (
            "the live share was never marked, so the revoke below proves "
            "nothing"
        )

        await store.revoke(minted.link.id)
        await mark_shared(app_state, infos)
        assert infos[0].spectator_expires_at is None, (
            "a revoked share still marks its session as shared: "
            f"{infos[0].spectator_expires_at!r}"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_an_install_with_no_spectator_store_still_lists_its_sessions():
    infos = _infos(SHARED, PRIVATE)
    assert len(infos) == 2, "nothing was listed, so nothing below is tested"

    await mark_shared(SimpleNamespace(), infos)

    assert [info.spectator_expires_at for info in infos] == [None, None], (
        "a listing with no spectator store invented a share mark"
    )


class _RaisingStore:

    def __init__(self):
        self.calls = 0

    async def live_expiry_by_session(self):
        self.calls += 1
        raise sqlite3.OperationalError("disk I/O error")


@pytest.mark.asyncio
async def test_a_broken_spectator_store_still_lists_its_sessions():
    store = _RaisingStore()
    infos = _infos(SHARED, PRIVATE)
    assert len(infos) == 2, "nothing was listed, so nothing below is tested"

    await mark_shared(SimpleNamespace(spectator_links=store), infos)

    assert store.calls == 1, (
        "the store was never asked, so the failing path was not exercised"
    )
    assert [info.spectator_expires_at for info in infos] == [None, None], (
        "a listing whose spectator store failed invented a share mark"
    )


@pytest.mark.asyncio
async def test_an_uninitialised_spectator_store_still_lists_its_sessions():
    store = SpectatorLinksStore(str(Path(tempfile.mkdtemp()) / "cloude.db"))
    infos = _infos(SHARED)
    assert len(infos) == 1, "nothing was listed, so nothing below is tested"

    await mark_shared(SimpleNamespace(spectator_links=store), infos)

    assert infos[0].spectator_expires_at is None, (
        "an uninitialised spectator store invented a share mark"
    )
