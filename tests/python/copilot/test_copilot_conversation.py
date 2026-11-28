
from __future__ import annotations

from src.core.copilot import conversation

UUID = "c898a589-2133-44ce-8953-387393edb10d"
OTHER = "b45a76b0-70b8-4021-bc74-4a432fc25e64"


def _held(monkeypatch, paths):
    monkeypatch.setattr(conversation, "open_vnode_paths", lambda pid: [((1, i), p) for i, p in enumerate(paths)])


def test_the_hold_file_of_this_pid_names_the_conversation(monkeypatch):
    _held(monkeypatch, ["/h/.copilot/logs/process-1-7.log", "/h/.copilot/session-state/%s/inuse.7.hold" % UUID])
    assert conversation.conversation_of_pid(7) == UUID


def test_another_pids_hold_and_a_non_uuid_folder_answer_nothing(monkeypatch):
    _held(monkeypatch, ["/h/.copilot/session-state/%s/inuse.8.hold" % OTHER, "/h/.copilot/session-state/notes/inuse.7.hold"])
    assert conversation.conversation_of_pid(7) is None


def test_a_gone_process_answers_nothing(monkeypatch):
    monkeypatch.setattr(conversation, "open_vnode_paths", lambda pid: None)
    assert conversation.conversation_of_pid(7) is None


def test_the_copilot_under_the_pane_is_found_and_nothing_outside_it(monkeypatch):
    _held(monkeypatch, ["/h/.copilot/session-state/%s/inuse.12.hold" % UUID])
    parents = {11: 10, 12: 11}
    commands = {11: "-zsh", 12: "/h/node_modules/@github/copilot-darwin-arm64/copilot --resume"}
    assert conversation.conversation_for_pane(10, parents, commands) == UUID
    assert conversation.conversation_for_pane(99, parents, commands) is None
    assert conversation.conversation_for_pane(None, parents, commands) is None
    assert conversation.conversation_for_pane(10, parents, {11: "-zsh", 12: "/bin/agy"}) is None
