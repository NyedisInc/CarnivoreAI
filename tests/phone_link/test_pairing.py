
import sqlite3

import pytest

from tests.phone_link.pairing_helpers import pair_device

from src.core.phone_link import pairing as pr


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = pr.PairingStore(path=tmp_path / "phone_link.db", clock=clock)
    yield s
    s.close()


def test_the_link_is_off_by_default_and_the_switch_persists(tmp_path):
    s = pr.PairingStore(path=tmp_path / "p.db")
    assert s.enabled is False
    s.set_enabled(True)
    s.close()
    assert pr.PairingStore(path=tmp_path / "p.db").enabled is True


def test_a_scan_makes_only_a_pending_pairing_and_the_code_makes_the_device(store):
    w = store.open_window()
    assert store.window_open() and len(w.code) == 8
    result = store.claim_secret(w.secret, "203.0.113.5", "iphone", "h.example")
    assert result.status == "pending" and result.handle
    assert store.device_count() == 0 and store.devices() == []
    assert not store.window_open() and store.pending_open()
    assert store.claim_secret(w.secret, "203.0.113.5") is None
    assert store.pairing_view() == {"state": "pending", "device": None, "locked": False}
    cookie = store.complete_pending(result.handle, "h.example")
    assert cookie and store.device_for_cookie(cookie, "h.example") and store.device_count() == 1
    assert store.complete_pending(result.handle, "h.example") is None
    assert not store.pending_open()


def test_the_window_code_also_goes_through_pending(store):
    w = store.open_window()
    result = store.claim_code(w.code.lower(), "203.0.113.5")
    assert result.status == "pending" and store.device_count() == 0 and not store.window_open()
    assert store.complete_pending(result.handle)


def test_a_pending_pairing_expires_leaving_nothing(store, clock):
    result = store.claim_secret(store.open_window().secret, "203.0.113.5")
    clock.now += pr.PENDING_SECONDS + 1
    assert not store.pending_open() and store.complete_pending(result.handle) is None
    assert store.begin_attempt(result.handle) is None
    assert store.device_count() == 0 and store.pairing_view()["state"] == "none"


def test_five_tries_kill_a_pending_pairing(store):
    handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
    for left in (4, 3, 2, 1):
        assert store.begin_attempt(handle) == left
        assert store.drop_if_spent(handle) is False
    assert store.begin_attempt(handle) == 0
    assert store.drop_if_spent(handle) is True
    assert store.begin_attempt(handle) is None and store.complete_pending(handle) is None


def test_the_cap_holds_however_earlier_tries_ended(store):
    handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
    assert [store.begin_attempt(handle) for _ in range(5)] == [4, 3, 2, 1, 0]
    assert store.begin_attempt(handle) is None and store.complete_pending(handle) is None


def test_two_wrong_code_deaths_lock_windows_until_acknowledged_and_a_timeout_does_not(store, clock):
    def die():
        handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
        for _ in range(5):
            store.begin_attempt(handle)
        store.drop_if_spent(handle)

    handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
    clock.now += pr.PENDING_SECONDS + 1
    assert store.pairing_view()["state"] == "none" and not store.locked()
    die()
    assert store.pairing_view()["state"] == "failed" and not store.locked()
    store.open_window()
    die()
    assert store.locked()
    with pytest.raises(pr.PairingLocked):
        store.open_window()
    store.acknowledge_failures()
    assert store.open_window() and not store.locked()


def test_failures_older_than_an_hour_do_not_lock(store, clock):
    for _ in range(2):
        handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
        for _ in range(5):
            store.begin_attempt(handle)
        store.drop_if_spent(handle)
        clock.now += pr.FAILURE_WINDOW_SECONDS / 2 + 1
    assert not store.locked() and store.open_window()


def test_a_wrong_handle_is_nothing(store):
    store.claim_secret(store.open_window().secret, "203.0.113.5")
    assert not store.has_pending("nope") and store.begin_attempt("nope") is None and store.complete_pending(None) is None


def test_a_new_window_or_a_cancel_drops_a_pending_pairing(store):
    handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
    store.open_window()
    assert not store.has_pending(handle)
    handle = store.claim_secret(store.open_window().secret, "203.0.113.5").handle
    store.close_window()
    assert not store.has_pending(handle)


def test_there_is_no_app_code_and_a_made_up_one_counts_a_miss(store):
    store.open_window()
    assert not hasattr(store, "issue_app_code") and not hasattr(pr, "APP_CODE_SECONDS")
    assert store.claim_code("ZXCV2345", "203.0.113.5") is None
    assert store._misses["203.0.113.5"]


def test_qr_secrets_rotate_two_live_at_most_each_for_120_seconds(store, clock):
    w = store.open_window()
    assert w.secret_expires_at == clock.now + pr.QR_SECRET_SECONDS
    clock.now += pr.QR_ROTATE_SECONDS
    second, _ = store.rotate_secret()
    clock.now += pr.QR_ROTATE_SECONDS
    third, _ = store.rotate_secret()
    live = [c for c in store._codes if c.kind == "window_secret"]
    assert len(live) == 2
    assert store.claim_secret(w.secret, "203.0.113.5") is None
    assert store.claim_secret(second, "203.0.113.5").status == "pending"
    assert not store.window_open() and store.claim_secret(third, "203.0.113.5") is None


def test_a_rotated_secret_never_outlives_its_window_and_none_rotates_without_one(store, clock):
    assert store.rotate_secret() is None
    store.open_window()
    clock.now += pr.WINDOW_SECONDS - 30
    _, expires = store.rotate_secret()
    assert expires == clock.now + 30
    clock.now += 31
    assert store.rotate_secret() is None


def test_a_claim_by_the_code_voids_every_secret(store):
    w = store.open_window()
    second, _ = store.rotate_secret()
    assert store.claim_code(w.code, "203.0.113.5").status == "pending"
    assert store.claim_secret(w.secret, "203.0.113.6") is None and store.claim_secret(second, "203.0.113.6") is None


def test_a_paired_browser_is_already_paired_and_nothing_is_consumed_or_counted(store):
    cookie = pair_device(store, "203.0.113.5", host="h.example")
    w = store.open_window()
    again = store.claim_secret(w.secret, "203.0.113.5", host="h.example", current_cookie=cookie)
    assert again.status == "already_paired" and again.handle is None
    assert store.window_open() and not store.pending_open() and store.device_count() == 1 and not store._misses
    dead = store.claim_secret("not-a-secret", "203.0.113.5", host="h.example", current_cookie=cookie)
    assert dead.status == "already_paired"


def test_a_cookie_for_another_host_is_treated_as_no_cookie(store):
    first = pair_device(store, "203.0.113.5", host="a.example")
    other = store.claim_secret(store.open_window().secret, "203.0.113.5", host="b.example", current_cookie=first)
    assert other.status == "pending" and store.device_count() == 1
    assert store.claim_secret("not-a-secret", "203.0.113.5", host="b.example", current_cookie=first) is None


def test_a_wrong_code_from_a_paired_browser_counts_a_miss_and_the_right_one_is_already_paired(store):
    first = pair_device(store, "203.0.113.5", host="h")
    w = store.open_window()
    assert store.claim_code("NOPE0000", "203.0.113.5", host="h", current_cookie=first) is None
    assert len(store._misses["203.0.113.5"]) == 1
    assert store.claim_code(w.code, "203.0.113.5", host="h", current_cookie=first).status == "already_paired"
    assert store.device_count() == 1 and store.window_open()


def test_the_last_completed_pairing_shows_to_the_owner_until_a_new_window_or_a_revoke(store):
    assert store.pairing_view() == {"state": "none", "device": None, "locked": False}
    w = store.open_window()
    assert store.pairing_view()["state"] == "open"
    handle = store.claim_secret(w.secret, "203.0.113.5", "iphone").handle
    cookie = store.complete_pending(handle)
    view = store.pairing_view()
    assert view["state"] == "claimed" and view["device"]["label"] == "iphone"
    store.revoke(store.device_for_cookie(cookie))
    assert store.pairing_view()["state"] == "none"
    store.open_window()
    assert store.pairing_view()["state"] == "open"


def test_five_misses_kill_a_code(store):
    w = store.open_window()
    for n in range(5):
        assert store.claim_code("WRONG%03d" % n, "198.51.100.%d" % n) is None
    assert store.claim_code(w.code, "203.0.113.5") is None
    assert store.window_open()
    assert store.claim_secret(w.secret, "203.0.113.5")


def test_wrong_secrets_never_kill_the_secret_and_empty_ip_entries_are_pruned(store):
    w = store.open_window()
    for n in range(6):
        assert store.claim_secret("guess%d" % n, "198.51.100.%d" % n) is None
    assert store.claim_secret(w.secret, "203.0.113.5")
    clock = store._clock
    store._clock = lambda: clock() + pr.IP_MISS_INTERVAL_SECONDS + 1
    store.open_window()
    store.claim_secret("x", "198.51.100.99")
    for n in range(6):
        store._throttle("198.51.100.%d" % n)
    assert all(store._misses.get("198.51.100.%d" % n) is None for n in range(6))


def test_an_address_over_its_miss_allowance_is_throttled(store):
    for n in range(pr.IP_MISS_LIMIT):
        store.open_window()
        assert store.claim_code("NOPE%04d" % n, "192.0.2.1") is None
    w = store.open_window()
    with pytest.raises(pr.Throttled):
        store.claim_secret(w.secret, "192.0.2.1")
    assert store.claim_secret(w.secret, "192.0.2.2")


def test_a_window_expires(store, clock):
    w = store.open_window()
    clock.now += pr.WINDOW_SECONDS + 1
    assert not store.window_open()
    assert store.claim_secret(w.secret, "203.0.113.5") is None
    assert store.claim_code(w.code, "203.0.113.5") is None


def test_only_the_cookie_digest_is_stored(store, tmp_path):
    cookie = pair_device(store, "203.0.113.5")
    store.close()
    raw = (tmp_path / "phone_link.db").read_bytes()
    assert cookie.encode() not in raw
    row = sqlite3.connect(str(tmp_path / "phone_link.db")).execute("SELECT cookie_hash FROM devices").fetchone()
    assert len(row[0]) == 64


def test_revoke_stops_the_cookie_and_runs_the_hooks(store):
    cookie = pair_device(store, "203.0.113.5")
    device = store.device_for_cookie(cookie)
    seen = []
    store.on_revoke.append(seen.append)
    assert store.revoke(device) is True
    assert store.device_for_cookie(cookie) is None and seen == [device]
    assert store.revoke(device) is False and store.device_count() == 0


def test_cookies_survive_a_restart(tmp_path):
    s = pr.PairingStore(path=tmp_path / "p.db")
    cookie = pair_device(s, "203.0.113.5")
    s.close()
    assert pr.PairingStore(path=tmp_path / "p.db").device_for_cookie(cookie)
