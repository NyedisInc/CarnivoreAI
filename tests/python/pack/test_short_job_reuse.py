
import json
import sqlite3

from src.core.pack.jobs.store import JobStore
from src.core.pack.reconnect import config


def test_block_cache_sees_a_changed_file_and_skips_an_unchanged_one(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({config.KEY: {"relay": True}}))
    reads = []
    real = config.config_writer.read_config
    monkeypatch.setattr(config.config_writer, "read_config", lambda p: reads.append(p) or real(p))
    assert config.relay_choice(path) is True and config.relay_choice(path) is True
    assert len(reads) == 1
    path.write_text(json.dumps({config.KEY: {"relay": False}}))
    assert config.relay_choice(path) is False
    config.set_relay(path, True)
    assert config.relay_choice(path) is True
    path.unlink()
    assert config.relay_choice(path) is None


def test_job_store_reuses_its_connection_on_a_thread(tmp_path, monkeypatch):
    opens = []
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: opens.append(a) or real(*a, **k))
    store = JobStore(tmp_path)
    for _ in range(5):
        store.list_jobs() if hasattr(store, "list_jobs") else store.agent_job_for_session("x")
    assert len(opens) == 1


def test_job_store_error_keeps_its_type_and_the_next_call_works(tmp_path):
    from src.core.pack.jobs.types import JobRecord

    store = JobStore(tmp_path)
    store.create_job(JobRecord(id="job_0123456789ab"))
    try:
        store.create_job(JobRecord(id="job_0123456789ab"))
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a duplicate id must raise IntegrityError")
    assert store.get_job("job_0123456789ab") is not None
