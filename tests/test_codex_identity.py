
from __future__ import annotations

from src.core.attention.codex_identity import codex_bind_conversation
from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP,
    SESSION_CLAUDE_UUID_SOURCES,
)

UUID = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"


class _FakeManager:
    def __init__(self):
        self.calls = []

    def record_claude_lifecycle_event(
        self, session_id, event_kind, payload, *, uuid_source, tmux_name
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "event_kind": event_kind,
                "payload": payload,
                "uuid_source": uuid_source,
                "tmux_name": tmux_name,
            }
        )
        return object()


def test_the_codex_source_is_a_recognised_provenance():
    assert (
        SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP in SESSION_CLAUDE_UUID_SOURCES
    )


def test_bind_writes_the_column_once_with_the_codex_source():
    mgr = _FakeManager()
    codex_bind_conversation(
        mgr, session_id="ses_1", tmux_name="cloude_x", thread_uuid=UUID
    )
    assert len(mgr.calls) == 1
    call = mgr.calls[0]
    assert call["uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP
    assert call["payload"]["session_id"] == UUID
    assert call["tmux_name"] == "cloude_x"


def test_bind_does_nothing_without_a_uuid_or_a_name():
    mgr = _FakeManager()
    codex_bind_conversation(
        mgr, session_id="ses_1", tmux_name="cloude_x", thread_uuid=None
    )
    codex_bind_conversation(
        mgr, session_id="ses_1", tmux_name=None, thread_uuid=UUID
    )
    assert mgr.calls == []


def test_measured_owned_conversation_rebinds_through_correlation_writer(tmp_path):
    from types import SimpleNamespace
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_models import SESSION_ORIGIN_ADOPTED
    from src.core.session_identity import record_instance
    from src.core.session_claude_correlate_bind import bind_correlated_uuid
    from tests.s7_helpers import migrated_connection, TEST_SOCKET, session_row

    old = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    conn = migrated_connection(tmp_path)
    with transaction(conn):
        record_instance(conn, socket=TEST_SOCKET, name="cloude_owned", epoch=1,
                        origin=SESSION_ORIGIN_ADOPTED, working_dir="/project")
        bind_correlated_uuid(conn, socket=TEST_SOCKET, name="cloude_owned", epoch=1,
                             claude_uuid=old)
    manager = SimpleNamespace(
        _writable_datastore_connection=lambda: connect(db_path_for(tmp_path)),
        tmux_socket_name=lambda: TEST_SOCKET,
    )
    result = codex_bind_conversation(
        manager, session_id="ses_1", tmux_name="cloude_owned", thread_uuid=UUID,
        epoch=1, pane_owned=True,
    )
    assert result.outcome == "rebound"
    assert session_row(conn, "cloude_owned")["claude_session_uuid"] == UUID
    again = codex_bind_conversation(
        manager, session_id="ses_1", tmux_name="cloude_owned", thread_uuid=UUID,
        epoch=1, pane_owned=True,
    )
    assert again.outcome == "already_known"
    conn.close()


def test_owned_bind_cannot_take_another_rows_conversation(tmp_path):
    from types import SimpleNamespace
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_models import SESSION_ORIGIN_ADOPTED
    from src.core.session_identity import record_instance
    from src.core.session_claude_correlate_bind import bind_correlated_uuid
    from tests.s7_helpers import migrated_connection, TEST_SOCKET, session_row

    old = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    conn = migrated_connection(tmp_path)
    with transaction(conn):
        for name, uuid in (("cloude_owned", old), ("cloude_other", UUID)):
            record_instance(conn, socket=TEST_SOCKET, name=name, epoch=1,
                            origin=SESSION_ORIGIN_ADOPTED, working_dir="/project")
            bind_correlated_uuid(conn, socket=TEST_SOCKET, name=name, epoch=1,
                                 claude_uuid=uuid)
    manager = SimpleNamespace(
        _writable_datastore_connection=lambda: connect(db_path_for(tmp_path)),
        tmux_socket_name=lambda: TEST_SOCKET,
    )
    result = codex_bind_conversation(
        manager, session_id="ses_1", tmux_name="cloude_owned", thread_uuid=UUID,
        epoch=1, pane_owned=True,
    )
    assert result.outcome == "already_known"
    assert session_row(conn, "cloude_owned")["claude_session_uuid"] == old
    conn.close()
