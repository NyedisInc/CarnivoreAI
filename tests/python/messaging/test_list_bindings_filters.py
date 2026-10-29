
from __future__ import annotations

import pytest

from src.core.messaging import store

from .conftest import UUID_A, UUID_B, bind


def test_an_empty_filter_is_refused_not_widened(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    with pytest.raises(ValueError):
        store.list_bindings(session_uuid="")
    with pytest.raises(ValueError):
        store.list_bindings(conversation_id="")


def test_none_means_no_filter_and_a_uuid_narrows(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    assert len(store.list_bindings()) == 2
    assert [b["session_uuid"] for b in store.list_bindings(session_uuid=UUID_A)] == [UUID_A]
