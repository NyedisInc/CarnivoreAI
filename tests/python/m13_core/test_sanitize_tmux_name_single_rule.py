from __future__ import annotations

import importlib

import pytest

from src.core import session_label, session_name_claim

DISAGREEING_LABELS = ("Media Compression", "client: acme", "build \U0001f680 now", "work(fork)", "!!!")

CALLER_MODULES = (
    "src.api.session_fork_routes",
    "src.api.session_restart_apply_routes",
    "src.api.session_conversations_routes",
)


@pytest.mark.parametrize("module_name", CALLER_MODULES)
def test_every_caller_binds_the_create_rule(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.sanitize_tmux_name is session_name_claim.sanitize_tmux_name


@pytest.mark.parametrize("label", DISAGREEING_LABELS)
def test_a_caller_names_a_label_exactly_as_create_does(label: str) -> None:
    fork = importlib.import_module("src.api.session_fork_routes")
    assert fork.sanitize_tmux_name(label) == session_name_claim.sanitize_tmux_name(label)


def test_session_label_no_longer_carries_a_second_rule() -> None:
    assert not hasattr(session_label, "sanitize_tmux_name")
    assert not hasattr(session_label, "unique_tmux_name")
