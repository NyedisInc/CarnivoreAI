
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from src.core import attention_reader as reader_module
from src.core.attention import screen_read
from src.core.attention.codex_stores import read_codex_transcript
from src.core.attention.watcher import WatchTarget
from src.core.attention_reader import AttentionEvidenceReader
from src.core.session_instance_index import InstanceFacts, InstanceIndex
from src.core.session_status_map import StatusMap

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def test_concurrent_workers_share_bulk_reads_and_capture_idle_codex(monkeypatch):
    counts = {"map": 0, "registry": 0, "capture": 0, "gather": 0}
    names = ["cloude_%d" % index for index in range(8)]

    def status_map():
        counts["map"] += 1
        return StatusMap({name: {"status": "running", "pid": 100 + index,
                                "created_at_epoch": 1}
                          for index, name in enumerate(names)},
                         complete=True, socket="cloude")

    def registry_index():
        counts["registry"] += 1
        return {}

    def capture(socket, name):
        counts["capture"] += 1
        return "Would you like to run the following command?"

    manager = SimpleNamespace(
        _build_tmux_status_map=status_map,
        _identity_for_instance=lambda name, epoch: {"agent_type": "codex"},
        _instance_index_for_listing=lambda *, socket, names: InstanceIndex(),
        tmux_socket_name=lambda: "cloude",
        _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(
            sessions={name: SimpleNamespace(agent_type="codex") for name in names},
            backends={name: SimpleNamespace(socket_name="cloude") for name in names},
        ),
    )
    monkeypatch.setattr(reader_module, "read_registry_index", registry_index)
    monkeypatch.setattr(reader_module, "read_instance_row",
                        lambda *args, **kwargs: {"claude_session_uuid": "uuid"})
    monkeypatch.setattr(reader_module, "resolve_primary_uuid", lambda *args, **kwargs: None)
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    def gather(*args, **kwargs):
        counts["gather"] += 1
        return None

    monkeypatch.setattr(reader_module, "gather_codex_evidence", gather)
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(capture))
    reader = AttentionEvidenceReader(manager, lambda sid: (sid, 1))
    with ThreadPoolExecutor(max_workers=4) as executor:
        evidence = list(executor.map(lambda name: reader(WatchTarget(name, name), NOW), names))
    assert counts == {"map": 1, "registry": 1, "capture": 8, "gather": 0}
    assert all(item.codex.pane.approval_dialog for item in evidence)
    assert evidence[0].identity == ("cloude", "cloude_0", 1, 100, "uuid")


def test_capture_reads_viewport_on_explicit_socket_only(monkeypatch):
    calls = []
    probes = []

    def run(command, **kwargs):
        if "capture-pane" not in command:
            probes.append(command)
            return SimpleNamespace(returncode=0, stdout="3.5a", stderr="")
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"prompt", stderr=b"")

    monkeypatch.setattr(screen_read.subprocess, "run", run)
    assert AttentionEvidenceReader._capture(None, "cloude_a") is None
    assert calls == []
    assert AttentionEvidenceReader._capture("cloude-test", "cloude_a") == "prompt"
    command, kwargs = calls[0]
    assert command[0].endswith("tmux") and command[1:3] == ["-L", "cloude-test"]
    assert kwargs["close_fds"] is False
    assert command[command.index("-S") + 1] == "0"
    assert kwargs["timeout"] == screen_read.CAPTURE_TIMEOUT_SECONDS
    assert all(p[1:2] == ["-V"] or p[1:3] == ["-L", "cloude-test"] for p in probes), probes


def test_codex_user_prompt_time_ignores_tool_and_assistant_messages(tmp_path):
    path = tmp_path / "rollout.jsonl"
    records = [
        {"timestamp": "2026-09-20T00:00:01Z", "type": "event_msg",
         "payload": {"type": "user_message", "message": "first"}},
        {"timestamp": "2026-09-20T00:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "user"}},
        {"timestamp": "2026-09-20T00:00:03Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant"}},
    ]
    path.write_text("\n".join(json.dumps(record) for record in records))
    facts = read_codex_transcript(path, now=NOW)
    assert facts.newest_user_prompt_at == NOW.replace(second=1)
    assert facts.last_append_at == NOW.replace(second=3)


def test_codex_rebind_requires_writer_owned_by_this_pane(monkeypatch):
    from src.core.attention import codex_stores

    candidates = [{"id": "mine", "archived": False},
                  {"id": "other", "archived": False}]
    monkeypatch.setattr(codex_stores, "_read_user_threads_at", lambda *args: candidates)
    monkeypatch.setattr(codex_stores, "_owned_writer_uuids",
                        lambda home, pids: {"mine"} if 12 in pids else set())
    parents = {12: 11, 11: 10, 22: 20}
    assert codex_stores.resolve_primary_uuid(
        "/codex", pane_current_path="/project", pane_title="", pane_pid=10,
        process_parents=parents,
    ) == "mine"
    assert codex_stores.resolve_primary_uuid(
        "/codex", pane_current_path="/project", pane_title="", pane_pid=30,
        process_parents=parents,
    ) is None


def test_codex_record_reads_uncheckpointed_live_wal(tmp_path):
    import sqlite3
    from src.core.attention.codex_stores import read_codex_record

    path = tmp_path / "thread_history_1.sqlite"
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE thread_turns (thread_id TEXT, status TEXT, rollout_ordinal INTEGER)")
        writer.execute("INSERT INTO thread_turns VALUES ('thread', 'inProgress', 1)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert read_codex_record(path, "thread", lock_live=True).verdict == "busy"
        writer.execute("UPDATE thread_turns SET status = 'completed'")
        writer.commit()
        assert path.with_name(path.name + "-wal").stat().st_size > 0
        assert read_codex_record(path, "thread", lock_live=True).verdict == "rest"
    finally:
        writer.close()


def test_owned_lock_probe_is_one_bounded_command(monkeypatch):
    from src.core.attention import codex_stores
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="p12\nn/codex/thread-writer-locks/mine.lock\nn/elsewhere/other.lock\n")

    import subprocess

    monkeypatch.setattr(subprocess, "run", run)
    assert codex_stores._owned_writer_uuids("/codex", {10, 11, 12}) == {"mine"}
    assert len(calls) == 1
    assert calls[0][0] == ["lsof", "-a", "-p", "10,11,12", "-Fn"]
    assert calls[0][1]["timeout"] == 1.0


def test_codex_subagent_notification_is_not_human_input(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(json.dumps({
        "timestamp": "2026-09-20T00:00:03Z", "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<subagent_notification>done</subagent_notification>"}
        ]},
    }))
    facts = read_codex_transcript(path, now=NOW)
    assert facts.newest_user_prompt_at is None
    assert facts.last_append_at == NOW.replace(second=3)


def test_reader_refuses_reused_name_before_reading_or_binding(monkeypatch):
    manager = SimpleNamespace(_registry=SimpleNamespace(
        backends={"ses": SimpleNamespace(socket_name="cloude")},
    ))
    reader = AttentionEvidenceReader(manager, lambda sid: ("cloude_a", 1))
    status_map = StatusMap({"cloude_a": {"status": "running", "pid": 10,
                                       "created_at_epoch": 2}},
                           complete=True, socket="cloude")
    monkeypatch.setattr(reader, "_pass", lambda now: (status_map, {}, []))
    assert reader(WatchTarget("ses", "cloude_a@1"), NOW) is None


def test_a_pass_reads_every_stored_row_once_not_per_pane(monkeypatch):
    names = ["cloude_%d" % index for index in range(6)]
    builds = []

    def index_for(*, socket, names):
        builds.append((socket, tuple(names)))
        return InstanceIndex({
            (name, 1): InstanceFacts(row_id=10 + i, agent_type="codex", agent_family="codex",
                                     agent_family_source="launched", claude_session_uuid="u%d" % i)
            for i, name in enumerate(names) if name != "cloude_5"
        }, complete=True)

    def per_row(*args, **kwargs):
        raise AssertionError("a per-pane connection was opened")

    manager = SimpleNamespace(
        _build_tmux_status_map=lambda: StatusMap(
            {name: {"status": "running", "pid": 100, "created_at_epoch": 1} for name in names},
            complete=True, socket="cloude"),
        _identity_for_instance=per_row,
        _writable_datastore_connection=per_row,
        _instance_index_for_listing=index_for,
        tmux_socket_name=lambda: "cloude",
        _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(
            sessions={name: SimpleNamespace(agent_type="codex") for name in names},
            backends={name: SimpleNamespace(socket_name="cloude") for name in names},
        ),
    )
    monkeypatch.setattr(reader_module, "read_registry_index", lambda: {})
    monkeypatch.setattr(reader_module, "resolve_primary_uuid", lambda *args, **kwargs: None)
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda socket, name: None))
    reader = AttentionEvidenceReader(manager, lambda sid: (sid, 1))
    with ThreadPoolExecutor(max_workers=3) as executor:
        evidence = list(executor.map(lambda name: reader(WatchTarget(name, name), NOW), names))
    assert builds == [("cloude", tuple(names))]
    assert evidence[0].identity[-1] == "u0" and evidence[0].agent_family == "codex"
    assert evidence[5].identity[-1] is None


def test_a_pane_the_index_did_not_ask_about_falls_back_to_its_own_reads(monkeypatch):
    calls = []
    manager = SimpleNamespace(
        _build_tmux_status_map=lambda: StatusMap({}, complete=False),
        _identity_for_instance=lambda name, epoch: calls.append(name) or {"agent_type": "codex"},
        _instance_index_for_listing=lambda **kw: (_ for _ in ()).throw(AssertionError("no index")),
        tmux_socket_name=lambda: "cloude",
        _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(sessions={"cloude_a": SimpleNamespace(agent_type="codex")},
                                  backends={"cloude_a": SimpleNamespace(socket_name="cloude")}),
    )
    monkeypatch.setattr(reader_module, "read_registry_index", lambda: {})
    monkeypatch.setattr(reader_module, "read_instance_row", lambda *a, **k: calls.append("row") or {})
    monkeypatch.setattr(reader_module, "resolve_primary_uuid", lambda *args, **kwargs: None)
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    reader = AttentionEvidenceReader(manager, lambda sid: (sid, 1))
    reader(WatchTarget("cloude_a", "cloude_a"), NOW)
    assert calls == ["row", "cloude_a"]
