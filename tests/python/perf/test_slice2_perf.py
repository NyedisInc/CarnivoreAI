
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from src.core.pack.relay import ledger_sync_store
from src.core.pipeline import lag
from src.core.provider_ledger import keychain_memo
from src.core.stats import answers, pack_scope, queries
from src.core.stats.store import StatsStore


def test_stats_db_perf_pragmas_and_covering_indexes(tmp_path: Path) -> None:
    store = StatsStore(tmp_path)
    store.initialize()
    with store.connect_read() as conn:
        assert conn.execute("PRAGMA cache_size").fetchone()[0] == -32000
        assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        for expected in (
            "usage_hour_src",
            "counter_hour_src",
            "usage_minute_src",
            "counter_minute_src",
            "quota_hour_acct_win",
        ):
            assert expected in indexes, f"missing index {expected}"

        for tbl in ("usage_hour", "counter_hour"):
            plan = " ".join(
                r[3]
                for r in conn.execute(
                    f"EXPLAIN QUERY PLAN SELECT s.conversation_id, u.t, p.name FROM dim_source s "
                    f"JOIN {tbl} u ON u.src = s.id JOIN dim_project p ON p.id = u.project "
                    "WHERE s.conversation_id IN (SELECT value FROM json_each('[\"c1\"]')) "
                    "GROUP BY 1, 2, 3 ORDER BY 3 DESC"
                ).fetchall()
            )
            assert f"SCAN {tbl}" not in plan, f"unexpected full table scan on {tbl}: {plan}"


def test_lag_of_single_flight_deduplicates_concurrent_cold_callers(tmp_path: Path, monkeypatch) -> None:
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def slow_compute(sd, dbp, plug):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2.0)
        return lag.Lag(files_tracked=10, lag_bytes=0, behind_conversations=0)

    plugin = MagicMock(id="stats_test_sf")
    lag.forget()
    monkeypatch.setattr(lag, "compute", slow_compute)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(lag.lag_of(tmp_path, tmp_path / "app.db", plugin)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    assert started.wait(timeout=2.0)
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(timeout=2.0)

    assert calls == 1
    assert len(results) == 4
    assert all(r.files_tracked == 10 for r in results)


def test_relay_rows_reads_credentials_file_without_keychain(tmp_path: Path, monkeypatch) -> None:
    import json
    from src.core.provider_ledger import credentials, relay_accounts
    from src.core.pack.relay import ledger_sync_view

    pdir = tmp_path / "relay-prof"
    pdir.mkdir()
    (pdir / ".credentials.json").write_text(json.dumps({
        "claudeAiOauth": {
            "accessToken": "test-oauth-placeholder-value",
            "expiresAt": int((time.time() + 3600) * 1000),
            "subscriptionType": "max",
        }
    }))
    from types import SimpleNamespace
    acct = SimpleNamespace(id="relay-prof", name="relay-prof")
    monkeypatch.setattr(relay_accounts, "relay_accounts", lambda: [acct])
    monkeypatch.setattr(relay_accounts, "profile_dir_for", lambda _a: str(pdir))
    monkeypatch.setattr(relay_accounts, "setup_complete", lambda _a: True)
    monkeypatch.setattr(ledger_sync_view, "directory", lambda: {})
    monkeypatch.setattr(credentials, "read_claude_credential", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("must not hit keychain")))

    rows = relay_accounts.relay_rows(stored={})
    assert len(rows) == 1
    assert rows[0].plan == "max"
    assert rows[0].credential_state == "ok"


def test_answers_ledger_l1_memory_cache_and_purge(tmp_path: Path) -> None:
    store = StatsStore(tmp_path)
    store.initialize()
    ledger = answers.ledger_for(store)
    ledger.purge()
    ledger.store_later("k1", "fp1", 1000, {"total": 42}, time.time(), usage_revision=1)
    view = MagicMock()
    view.connect.side_effect = AssertionError("L1 cache hit should not touch SQLite")
    row = ledger.read(view, "k1")
    assert row is not None and row.payload == {"total": 42}
    answers.wait_idle()
    ledger.purge()
    assert "k1" not in ledger._mem
