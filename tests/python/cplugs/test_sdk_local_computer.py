
from __future__ import annotations

import src.core.federation.discovery as discovery
from src.cplugs.sdk import computer


def test_the_name_is_asked_of_the_system_once(monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(discovery, "local_host_name", lambda: asked.append(1) or " Mac Mini M4 ")
    computer.local_computer.cache_clear()
    try:
        assert computer.local_computer() == "Mac-Mini-M4" and computer.local_computer() == "Mac-Mini-M4"
        assert len(asked) == 1
    finally:
        computer.local_computer.cache_clear()
