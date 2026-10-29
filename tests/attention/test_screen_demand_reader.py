
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core import attention_reader as reader_module
from src.core.attention import screen_demand as sd
from src.core.attention.record_identity import RecordIdentity
from src.core.attention.registry_index import registry_for_session
from src.core.attention.transcript_facts import FACTS_NO_RECORD, TranscriptFacts
from src.core.attention.watcher import WatchTarget
from src.core.attention_reader import AttentionEvidenceReader
from src.core.background_work.measured import UNREADABLE
from src.core.session_instance_index import InstanceIndex
from src.core.session_status_map import StatusMap

from tests.attention.test_screen_demand import PROC_START, record

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
NAME = "carnivore_a"


class Rig:

    def __init__(self, monkeypatch) -> None:
        self.mono = 1000.0
        self.registry = record("busy")
        self.captures = 0
        self.ask_open = False
        self.passes = 0
        manager = SimpleNamespace(
            _build_tmux_status_map=lambda: StatusMap(
                {NAME: {"status": "running", "pid": 77, "created_at_epoch": 1}},
                complete=True, socket="cloude-test"),
            _identity_for_instance=lambda name, epoch: {"agent_type": "claude"},
            _instance_index_for_listing=lambda *, socket, names: InstanceIndex(),
            tmux_socket_name=lambda: "cloude-test",
            _wrappers_reader=lambda: [],
            _registry=SimpleNamespace(sessions={"ses_a": SimpleNamespace(agent_type="claude")},
                                      backends={"ses_a": SimpleNamespace(socket_name="cloude-test")}),
        )
        monkeypatch.setattr(reader_module, "read_registry_index", lambda: {NAME: self.registry})
        monkeypatch.setattr(reader_module, "read_instance_row", lambda *a, **k: {})
        monkeypatch.setattr(reader_module, "attention_reads_for_name",
                            lambda *a, **k: (self.registry, TranscriptFacts(verdict=FACTS_NO_RECORD)))
        monkeypatch.setattr(reader_module, "time", SimpleNamespace(
            monotonic=lambda: self.mono, time=lambda: 1792079000.0 + self.mono))
        monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *a: {})
        monkeypatch.setattr(AttentionEvidenceReader, "_process_snapshot", lambda *a: UNREADABLE)
        monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(self._capture))
        identity = RecordIdentity(lstarts=lambda pids: {pid: PROC_START for pid in pids})
        self.reader = AttentionEvidenceReader(manager, lambda sid: (NAME, 1),
                                              ask_open=lambda key: self.ask_open,
                                              record_identity=identity)

    def _capture(self, socket, name, history=0):
        self.captures += 1
        return "✻ Working… (3s · esc to interrupt)\n"

    def read(self, seconds=2.0, **kwargs):
        self.mono += seconds
        self.passes += 1
        return self.reader(WatchTarget("ses_a", NAME + "@1"), NOW + timedelta(seconds=self.passes),
                           **kwargs)


def test_busy_reads_once_then_skips_until_the_safety_look(monkeypatch):
    rig = Rig(monkeypatch)
    first = rig.read()
    assert first.screen_decision.reason == sd.READ_SAFETY_LOOK and rig.captures == 1
    skipped = rig.read()
    assert skipped.screen_decision == sd.ScreenDecision(False, sd.SKIP_RECORD)
    assert rig.captures == 1 and skipped.pane is None and skipped.dialog is None
    for _ in range(13):
        rig.read()
    assert rig.captures == 1
    rig.read(seconds=sd.SAFETY_LOOK_SECONDS - 26.0)
    assert rig.captures == 2


def test_waiting_no_file_and_an_open_ask_each_read(monkeypatch):
    rig = Rig(monkeypatch)
    rig.read()
    rig.registry = record("waiting", waiting_for="permission prompt")
    assert rig.read().screen_decision.reason == sd.READ_WAITING and rig.captures == 2
    rig.registry = record("busy")
    assert rig.read().screen_decision.read is False
    rig.ask_open = True
    assert rig.read().screen_decision.reason == sd.READ_ASK_OPEN and rig.captures == 3
    rig.ask_open = False
    rig.registry = registry_for_session(tmux_name=NAME, index={})
    assert rig.read().screen_decision.reason == sd.READ_NO_RECORD and rig.captures == 4


def test_read_fresh_forces_a_capture(monkeypatch):
    rig = Rig(monkeypatch)
    rig.read()
    rig.mono += 2.0
    evidence = rig.reader.read_fresh(WatchTarget("ses_a", NAME + "@1"), NOW + timedelta(minutes=5))
    assert evidence.screen_decision.reason == sd.READ_FORCED and rig.captures == 2


def test_an_unproven_record_reads_every_pass(monkeypatch):
    rig = Rig(monkeypatch)
    rig.registry = record("busy", proc_start=None)
    for _ in range(3):
        assert rig.read().screen_decision.reason == sd.READ_IDENTITY_UNPROVEN
    assert rig.captures == 3
