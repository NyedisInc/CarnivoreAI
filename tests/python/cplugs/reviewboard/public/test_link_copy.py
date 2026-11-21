
from __future__ import annotations

import asyncio
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
import structlog
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.api_keys.fence import fenced_family
from src.plugins.reviewboard.public import links, minting
from src.plugins.sdk import CplugStorage, StorageSpec
from tests.python.cplugs.reviewboard.public.read_harness import edge, get
from tests.python.cplugs.reviewboard.boards import SIDECAR

SLUG = SIDECAR["board"]["slug"]
BASE = "/api/v1/cplugs/reviewboard/public/links"


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()


def test_migration_three_carries_a_version_two_file_with_rows(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    folder.mkdir(mode=0o700)
    with sqlite3.connect(folder / "links.db") as conn:
        conn.executescript(links.MIGRATIONS[0])
        conn.executescript(links.MIGRATIONS[1])
        conn.execute("INSERT INTO links (id, secret_hash, board, revision, mode, created_at, expires_at, content_sha256) VALUES ('id1', 'h', 'b', 'r1', 'follow', 1, 9999999999, 'x')")
        conn.execute("INSERT INTO link_revisions (link_id, revision) VALUES ('id1', 'r1')")
        conn.execute("PRAGMA user_version = 2")
    storage = CplugStorage(folder, StorageSpec(db="links.db", migrations=links.MIGRATIONS, private=True))
    with storage.connect(False) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3 == len(links.MIGRATIONS)
    [row] = links.list_links(storage)
    assert (row.id, row.mode, row.access, row.copyable) == ("id1", "follow", "answer", False)
    assert links.token_of(storage, "id1") is None


def test_a_minted_link_can_be_copied_again_and_the_copy_opens_the_same_page(read_env, store, owner) -> None:
    made = owner.post(BASE, json={"board": SLUG, "ttl": "1d"}).json()
    listed = owner.get(BASE, params={"board": SLUG}).json()["links"]
    assert [row["copyable"] for row in listed] == [True]
    copied = owner.get(f"{BASE}/{made['link']['id']}/token")
    assert copied.status_code == 200 and copied.json() == {"token": made["token"]}
    assert copied.headers["cache-control"] == "no-store"
    assert get(edge(), "/api/board", copied.json()["token"]).status == 200


def test_a_link_made_before_copy_was_kept_has_no_copy(read_env, store, owner) -> None:
    token = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned"))["token"]
    link_id = token.removeprefix("pbl_").split(".")[0]
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE links SET token = NULL WHERE id = ?", (link_id,))
    assert [row["copyable"] for row in owner.get(BASE).json()["links"]] == [False]
    refused = owner.get(f"{BASE}/{link_id}/token")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "publicboard_not_copyable"
    assert owner.get(f"{BASE}/nope/token").status_code == 404


def test_an_ended_link_is_not_copied(read_env, store, owner) -> None:
    made = owner.post(BASE, json={"board": SLUG, "ttl": "1d"}).json()
    assert owner.delete(f"{BASE}/{made['link']['id']}").status_code == 200
    assert owner.get(f"{BASE}/{made['link']['id']}/token").status_code == 409


def test_the_token_is_in_no_visitor_answer_and_no_log_line(read_env, store, owner) -> None:
    with structlog.testing.capture_logs() as logged:
        made = owner.post(BASE, json={"board": SLUG, "ttl": "1d"}).json()
        owner.get(BASE)
        owner.get(f"{BASE}/{made['link']['id']}/token")
    secret = made["token"].split(".")[1]
    assert secret not in str(logged) and made["token"] not in str(logged)
    for path in ("/api/board", "/api/next", "/api/draft"):
        answer = get(edge(), path, made["token"], extra=(("Carnivore-Revision", "r1"),))
        assert secret.encode() not in answer.body and made["token"].encode() not in answer.body, path
    shell = get(edge(), "/", None)
    assert secret.encode() not in shell.body
    assert secret not in str(owner.get(BASE).json())


def test_the_copy_route_is_the_owners_alone(read_env, store) -> None:
    assert fenced_family(f"{BASE}/abc/token") == fenced_family(BASE) == "public review links and their visitors"
    with TestClient(read_env.app) as anonymous:
        assert anonymous.get(f"{BASE}/abc/token").status_code in (401, 403)


def test_the_file_and_folder_stay_closed_with_tokens_inside(read_env, store, owner) -> None:
    owner.post(BASE, json={"board": SLUG, "ttl": "1d"})
    assert stat.S_IMODE(store.db_path.stat().st_mode) == 0o600 and stat.S_IMODE(store.path.stat().st_mode) == 0o700


def _stored_token(storage: Any, link_id: str) -> Any:
    with storage.connect(False) as conn:
        return conn.execute("SELECT token FROM links WHERE id = ?", (link_id,)).fetchone()[0]


def test_revoking_a_link_wipes_its_kept_token(read_env, store) -> None:
    made = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned"))
    link_id = made["link"].id
    assert _stored_token(store, link_id) == made["token"]
    links.revoke_link(store, link_id)
    assert _stored_token(store, link_id) is None and links.token_of(store, link_id) is None


def test_revoking_a_board_or_every_link_wipes_the_tokens(read_env, store) -> None:
    ids = [asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned"))["link"].id for _ in range(2)]
    links.revoke_board(store, SLUG)
    assert [_stored_token(store, i) for i in ids] == [None, None]


def test_an_expired_link_s_token_is_wiped_on_the_next_sweep_and_never_read_back(read_env, store) -> None:
    made = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1h", "pinned"))
    link_id = made["link"].id
    later = made["link"].expires_at + 5
    assert links.token_of(store, link_id, now=later) is None
    assert links.check(store, made["token"], now=later).state == "ended"
    assert _stored_token(store, link_id) is None


def test_a_locked_database_during_the_sweep_never_changes_an_ended_answer(read_env, store) -> None:
    made = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1h", "pinned"))
    later = made["link"].expires_at + 5
    holder = sqlite3.connect(str(store.path / "links.db"), timeout=0.1)
    holder.execute("BEGIN IMMEDIATE")
    try:
        assert links.check(store, made["token"], now=later).state == "ended"
    finally:
        holder.rollback()
        holder.close()
    assert _stored_token(store, made["link"].id) == made["token"]
    assert links.check(store, made["token"], now=later).state == "ended" and _stored_token(store, made["link"].id) is None


def test_a_failing_sweep_never_refuses_a_mint(read_env, store, monkeypatch) -> None:
    def locked(*_a: Any, **_k: Any) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(links, "sweep_ended", locked)
    made = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned"))
    assert made["token"].startswith("pbl_")
