
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

import asyncio

import structlog

from src.cplugs.publicboard import capability, deps, health, links, minting, ratelimit, resolve, routes_owner
from src.cplugs.publicboard.read import READER
from src.cplugs.publicboard.resolve import Resolver
from src.cplugs.reviewboard import public_port, viewer
from src.cplugs.reviewboard.layers import inject as layer_inject
from src.cplugs.sdk.board_public import PublicBoardUnavailable
from src.cplugs.sdk.file_secrets import ScanTimeout
from tests.python.cplugs.publicboard.read_harness import add_revision, edge, get, mint_token, rewrite
from tests.python.cplugs.publicboard.test_public_read import FAKE_KEY
from tests.python.cplugs.reviewboard.boards import PAGE

LOCKED = "default-src 'none'; frame-ancestors 'none'"


def assert_fixed(answer: Any, status: int, state: str) -> None:
    assert answer.status == status and answer.json() == {"state": state}
    assert answer.headers["x-content-type-options"] == "nosniff" and answer.headers["cache-control"] == "no-store"
    assert answer.headers["content-security-policy"] == LOCKED and answer.headers["referrer-policy"] == "no-referrer"


def ticket_of(token: str) -> str:
    return get(edge(), "/api/board", token).json()["views"][0]["frame"]


def revoke_all_links(store: Any) -> None:
    links.revoke_all(store)



@pytest.mark.parametrize("error", [PermissionError("links.db folder"), FileNotFoundError("links.db")])
def test_an_unreadable_links_database_is_the_fixed_503_with_every_header(read_env, store, monkeypatch, error: OSError) -> None:
    token = mint_token(store)
    monkeypatch.setattr(links, "check", lambda *a, **k: (_ for _ in ()).throw(error))
    assert_fixed(get(edge(), "/api/board", token), 503, "unavailable")


def test_an_unreadable_links_database_on_a_frame_is_the_fixed_503(read_env, store, monkeypatch) -> None:
    url = ticket_of(mint_token(store))
    monkeypatch.setattr(links, "active", lambda *a, **k: (_ for _ in ()).throw(PermissionError("x")))
    assert_fixed(get(edge(), url), 503, "unavailable")


def test_a_broken_bridge_file_is_the_fixed_503_on_the_frame_and_harmless_on_the_data(read_env, store, monkeypatch) -> None:
    token = mint_token(store)
    url = ticket_of(token)
    monkeypatch.setattr(viewer, "BRIDGE_PATH", Path("/nonexistent/bridge.js"))
    assert_fixed(get(edge(), url), 503, "unavailable")
    assert get(edge(), "/api/board", token).status == 200


def test_a_broken_layer_runtime_raises_the_board_unavailable_not_a_bare_oserror(monkeypatch) -> None:
    layered = SimpleNamespace(layer=SimpleNamespace(model_dump=lambda mode: {}))
    monkeypatch.setattr(layer_inject, "layer_bytes", lambda layer: (_ for _ in ()).throw(FileNotFoundError("layer-core.js")))
    with pytest.raises(PublicBoardUnavailable):
        public_port._public_page(PAGE, layered, "main")  # type: ignore[arg-type]


def test_a_missing_shell_file_is_the_fixed_503(read_env, monkeypatch) -> None:
    from src.cplugs.publicboard import assets

    monkeypatch.setattr(assets, "PUBLIC_DIR", Path("/nonexistent"))
    assets.asset_file.cache_clear()
    try:
        assert_fixed(get(edge(), "/"), 503, "unavailable")
    finally:
        assets.asset_file.cache_clear()


def test_the_three_dependency_errors_share_one_base() -> None:
    assert all(issubclass(e, deps.PublicReadError) for e in (deps.Unavailable, deps.BoardMissing, deps.Unscannable))



def test_a_page_edited_behind_the_link_ends_its_frame_too(read_env, store, folder: Path) -> None:
    url = ticket_of(mint_token(store))
    assert get(edge(), url).status == 200
    page = PAGE + b"<p>changed after the scan</p>"
    (folder / "r001.html").write_bytes(page)

    def fix(raw: Any) -> None:
        view = raw["revisions"][0]["views"][0]
        view["sha256"], view["bytes"] = hashlib.sha256(page).hexdigest(), len(page)

    rewrite(folder, fix)
    dead = get(edge(), url)
    assert dead.status == 404 and dead.json() == {"state": "ended"} and b"changed after" not in dead.body


def test_a_ticket_for_an_older_revision_serves_nothing_once_a_follow_link_moved(read_env, store, folder: Path) -> None:
    follow = mint_token(store, mode="follow")
    old = ticket_of(follow)
    add_revision(folder, PAGE + b"<p>second</p>")
    moved = get(edge(), "/api/board", follow).json()
    assert moved["revision"] == "r2" and get(edge(), moved["views"][0]["frame"]).status == 200
    stale = get(edge(), old)
    assert stale.status == 404 and stale.json() == {"state": "invalid"} and b"second" not in stale.body



def test_advance_never_moves_a_pinned_or_a_revoked_link(read_env, store) -> None:
    pinned, follow = mint_token(store), mint_token(store, mode="follow")
    pinned_id, follow_id = (t.removeprefix("pbl_").split(".")[0] for t in (pinned, follow))
    assert links.advance(store, pinned_id, "r2", "f" * 64) == 0
    links.revoke_link(store, follow_id)
    assert links.advance(store, follow_id, "r2", "f" * 64) == 0
    assert {r.id: (r.revision, r.content_sha256 == "f" * 64) for r in links.list_links(store)} == {pinned_id: ("r1", False), follow_id: ("r1", False)}


def test_a_link_revoked_while_its_newer_revision_is_scanned_ends(read_env, store, folder: Path, monkeypatch) -> None:
    follow = mint_token(store, mode="follow")
    link_id = follow.removeprefix("pbl_").split(".")[0]
    add_revision(folder, PAGE + b"<p>second</p>")
    real = minting.scan_texts

    def scan_then_revoke(texts: Any) -> Any:
        result = real(texts)
        links.revoke_link(store, link_id)
        return result

    monkeypatch.setattr(minting, "scan_texts", scan_then_revoke)
    assert get(edge(), "/api/board", follow).json() == {"state": "ended"}
    (row,) = links.list_links(store)
    assert row.revision == "r1"


def test_a_trailing_segment_on_a_frame_path_is_refused_at_the_edge(read_env, store) -> None:
    url = ticket_of(mint_token(store))
    assert get(edge(), url).status == 200
    for longer in (url + "/x", url + "x", url + "/", url + ".."):
        got = get(edge(), longer)
        assert got.status in (400, 404) and got.body == b"", longer


def test_the_rate_limit_table_is_bounded_and_drops_expired_windows_first(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 3)
    now = [0.0]
    limiter = ratelimit.RateLimiter(1, clock=lambda: now[0])
    for key in "abcd":
        limiter.allow(key)
    assert len(limiter._hits) == ratelimit.low_water_keys() and limiter.allow("a") is True, "the oldest key was evicted, so it starts a fresh window"
    now[0] = 1000.0
    limiter = ratelimit.RateLimiter(1, clock=lambda: now[0])
    limiter.allow("old1"), limiter.allow("old2")
    now[0] = 1000.0 + ratelimit.WINDOW_S + 1
    limiter.allow("live1"), limiter.allow("live2")
    assert set(limiter._hits) == {"live1", "live2"} and limiter.allow("live1") is False, "expired windows go first and live counts survive"


def test_the_refused_revision_memory_is_bounded(read_env, store, folder: Path, monkeypatch) -> None:
    monkeypatch.setattr(resolve, "MAX_REJECTED", 2)
    follow = mint_token(store, mode="follow")
    for number in range(3):
        add_revision(folder, PAGE + f"<!-- {FAKE_KEY}{number} -->".encode())
        assert get(edge(), "/api/board", follow).json()["revision"] == "r1"
    assert len(READER.resolver._rejected) == 2



def test_a_scan_timeout_is_remembered_for_a_minute_and_then_tried_again(read_env, store, folder: Path, monkeypatch) -> None:
    now = [100.0]
    READER.resolver = Resolver(READER.resolver.deps, clock=lambda: now[0])
    follow = mint_token(store, mode="follow")
    add_revision(folder, PAGE + b"<p>second</p>")
    outcomes: List[str] = []
    real = minting.scan_texts

    def flaky(texts: Any) -> Any:
        outcomes.append("scan")
        if len(outcomes) == 1:
            raise ScanTimeout()
        return real(texts)

    monkeypatch.setattr(minting, "scan_texts", flaky)
    assert get(edge(), "/api/board", follow).json()["revision"] == "r1"
    now[0] += resolve.UNSCANNABLE_RETRY_S - 1
    assert get(edge(), "/api/board", follow).json()["revision"] == "r1" and len(outcomes) == 1, "not rescanned inside the minute"
    now[0] += 2
    assert get(edge(), "/api/board", follow).json()["revision"] == "r2" and len(outcomes) == 2, "tried again after it, and cleared"


def test_a_real_credential_hit_is_never_retried(read_env, store, folder: Path, monkeypatch) -> None:
    now = [100.0]
    READER.resolver = Resolver(READER.resolver.deps, clock=lambda: now[0])
    follow = mint_token(store, mode="follow")
    add_revision(folder, PAGE + f"<!-- {FAKE_KEY} -->".encode())
    seen: List[int] = []
    real = minting.scan_texts
    monkeypatch.setattr(minting, "scan_texts", lambda texts: seen.append(1) or real(texts))
    get(edge(), "/api/board", follow)
    now[0] += 10 ** 6
    assert get(edge(), "/api/board", follow).json()["revision"] == "r1" and len(seen) == 1



def test_the_fingerprint_comparison_and_hash_run_in_a_thread(read_env, store, folder: Path) -> None:
    import threading

    main = threading.get_ident()
    seen: List[int] = []
    inner = READER.resolver.deps

    def spy(fn: Any) -> Any:
        return lambda *a: seen.append(threading.get_ident()) or fn(*a)

    READER.resolver = Resolver(deps.ReadDeps(**{**inner.__dict__, "matches": spy(inner.matches), "fingerprint": spy(inner.fingerprint)}))
    follow = mint_token(store, mode="follow")
    add_revision(folder, PAGE + b"<p>second</p>")
    assert get(edge(), "/api/board", follow).status == 200
    assert len(seen) >= 2 and main not in seen



def test_a_request_without_a_forwarded_address_is_a_fixed_400_not_a_shared_bucket(read_env, store) -> None:
    token = mint_token(store)
    for extra in ((), (("X-Forwarded-For", "not-an-address"),), (("X-Forwarded-For", "1.2.3.4,"),)):
        assert_fixed(get(edge(), "/api/board", token, extra=extra, forwarded=None), 400, "misrouted")
    assert get(edge(), "/api/board", token).status == 200


def test_ipv6_visitors_are_bucketed_by_their_slash_64(read_env, store) -> None:
    token = mint_token(store)
    READER.resolver = Resolver(READER.resolver.deps, per_client=2)

    def at(address: str) -> int:
        return get(edge(), "/api/board", token, forwarded=address).status

    assert [at("2001:db8:1:2::1"), at("2001:db8:1:2:ffff::9"), at("2001:db8:1:2:abcd::5")] == [200, 200, 429]
    assert at("2001:db8:1:3::1") == 200, "another /64 has its own budget"


def test_client_key_forms() -> None:
    def scope(value: str) -> dict:
        return {"headers": [(b"x-forwarded-for", value.encode())]}

    assert capability.client_key(scope("9.9.9.9, 198.51.100.7")) == "198.51.100.7"
    assert capability.client_key(scope("2001:db8:1:2:aaaa::1")) == "2001:db8:1:2::/64"
    assert capability.client_key({"headers": []}) is None



def key_of(value: str) -> Any:
    return capability.client_key({"headers": [(b"x-forwarded-for", value.encode())]})


def test_ipv4_mapped_visitors_keep_their_own_ipv4_bucket() -> None:
    first, second = key_of("::ffff:198.51.100.7"), key_of("::ffff:203.0.113.9")
    assert first == "198.51.100.7" and second == "203.0.113.9" and first != second
    assert key_of("::ffff:198.51.100.7") == key_of("198.51.100.7"), "the same visitor, mapped or not, is one bucket"


@pytest.mark.parametrize("entry,expected", [("203.0.113.9:5555", "203.0.113.9"), ("[2001:db8::1]:443", "2001:db8::/64"), ("[2001:db8::1]", "2001:db8::/64"),
                                            ("[::ffff:198.51.100.7]:80", "198.51.100.7"), ("1.2.3.4, 203.0.113.9:80", "203.0.113.9")])
def test_a_port_suffix_is_dropped_before_the_address_is_read(entry: str, expected: str) -> None:
    assert key_of(entry) == expected


@pytest.mark.parametrize("entry", ["", "garbage", "garbage:80", "1.2.3.4:99999x", "[bad]:1", "1.2.3.4:5:6"])
def test_an_unreadable_entry_has_no_key(entry: str) -> None:
    assert key_of(entry) is None


def test_the_report_names_the_shape_and_never_the_text() -> None:
    def report(*lines: str) -> Any:
        return capability.forwarded_report({"headers": [(b"x-forwarded-for", line.encode()) for line in lines], "client": ("203.0.113.11", 1)})

    assert (report().shape, report().present, report().copies, report().peer) == ("missing", False, 0, "203.0.113.11")
    assert report("").shape == "empty" and report("garbage:80").shape == "has_port" and report("nonsense").shape == "not_an_ip"
    two = report("1.1.1.1", "nonsense")
    assert two.copies == 2 and two.shape == "not_an_ip" and "nonsense" not in repr(two)


def test_the_missing_address_log_is_throttled_to_once_a_minute_with_a_running_count() -> None:
    now, wall = [10.0], [1000.0]
    record = health.ProxyHealth(clock=lambda: now[0], wall=lambda: wall[0])
    report = capability.ForwardedReport("203.0.113.11", True, 2, "has_port")
    with structlog.testing.capture_logs() as logs:
        for _ in range(5):
            record.missing(report)
        now[0] += health.LOG_EVERY_S - 1
        record.missing(report)
        now[0] += 2
        record.missing(report)
    lines = [entry for entry in logs if entry["event"] == "publicboard_no_forwarded_address"]
    assert [entry["count"] for entry in lines] == [1, 7]
    assert lines[0]["peer"] == "203.0.113.11" and lines[0]["header_present"] is True and lines[0]["copies"] == 2 and lines[0]["shape"] == "has_port"
    assert lines[0]["log_level"] == "warning"


def test_the_owner_status_says_the_proxy_is_not_forwarding_and_clears_itself(read_env, store, monkeypatch) -> None:
    record = health.ProxyHealth()
    monkeypatch.setattr(routes_owner, "HEALTH", record)
    READER.resolver = Resolver(READER.resolver.deps, health=record)
    token = mint_token(store)
    assert asyncio.run(routes_owner.status())["forwarding_ok"] is True
    assert_fixed(get(edge(), "/api/board", token, forwarded=None), 400, "misrouted")
    seen = asyncio.run(routes_owner.status())
    assert seen["forwarding_ok"] is False and seen["message"] == "the proxy is not forwarding the visitor address" and seen["missing_count"] == 1
    assert seen["last_missing_at"] is not None and seen["listening"] is False
    import time

    time.sleep(0.01)
    assert get(edge(), "/api/board", token).status == 200
    assert asyncio.run(routes_owner.status())["forwarding_ok"] is True


def test_the_shell_has_its_own_words_for_a_misrouted_page(read_env) -> None:
    script = get(edge(), "/app.js").body.decode()
    assert "\n    misrouted:" in script and "not set up correctly" in script and "MESSAGES[res.body.state]" in script
