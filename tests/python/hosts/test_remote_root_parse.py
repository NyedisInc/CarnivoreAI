
from __future__ import annotations

import pytest

from src.core.hosts.identity import RemoteRootConflict, parse_remote_root, remote_project_root, resolve_create_target


def test_parse_inverts_remote_project_root() -> None:
    assert parse_remote_root(remote_project_root("studio", "/home/alex/api")) == ("studio", "/home/alex/api")


@pytest.mark.parametrize("value", [None, "", "/Users/me/api", "peer://peer-ab12/w", "ssh://studio", "ssh://Bad_Key/x", "ssh://local/x"])
def test_parse_refuses_what_is_not_an_ssh_root(value) -> None:
    assert parse_remote_root(value) is None


def test_resolve_reads_the_root_when_no_host_is_named() -> None:
    assert resolve_create_target(None, "ssh://studio/home/alex/api") == ("studio", "/home/alex/api")
    assert resolve_create_target("studio", "ssh://studio/home/alex/api") == ("studio", "/home/alex/api")


def test_resolve_leaves_a_plain_create_alone() -> None:
    assert resolve_create_target(None, "/Users/me/api") == (None, "/Users/me/api")
    assert resolve_create_target("studio", "/home/alex") == ("studio", "/home/alex")


def test_resolve_refuses_a_different_computer() -> None:
    with pytest.raises(RemoteRootConflict):
        resolve_create_target("odin", "ssh://studio/home/alex/api")
