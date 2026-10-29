
from __future__ import annotations

import asyncio
import threading

from src.core.crosstalk import directory


def card(name: str, i: int) -> dict:
    return {"name": name, "id": f"ses_{i}", "session_uuid": f"uuid-{i}", "tmux_name": f"t{i}", "former_names": []}


CARDS = [card("bot-Misc UI", 1), card("Ledgerbot", 2), card("Carnivore Server", 3)]


def test_an_exact_name_never_reaches_difflib(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("difflib must not run when an exact tier matched")

    monkeypatch.setattr(directory.difflib, "SequenceMatcher", boom)
    result = directory.resolve_handle("@bot-misc ui", CARDS)
    assert result.tier == "label" and result.matches[0]["id"] == "ses_1"


def test_fuzzy_still_answers_when_nothing_else_matches():
    result = directory.resolve_handle("carnivor sever", CARDS)
    assert result.tier == "fuzzy" and result.matches[0]["id"] == "ses_3"
    assert directory.resolve_handle("zzzzqqq", CARDS).matches == []


def test_async_twin_gives_the_same_answer_and_runs_fuzzy_in_a_thread(monkeypatch):
    threads: list = []
    real = directory._resolve_fuzzy
    want_fuzzy = directory.resolve_handle("carnivor sever", CARDS)
    monkeypatch.setattr(directory, "_resolve_fuzzy", lambda q, c: threads.append(threading.current_thread()) or real(q, c))

    async def scenario():
        fuzzy = await directory.resolve_handle_async("carnivor sever", CARDS)
        exact = await directory.resolve_handle_async("Ledgerbot", CARDS)
        return fuzzy, exact

    fuzzy, exact = asyncio.run(scenario())
    assert fuzzy == want_fuzzy
    assert exact == directory.resolve_handle("Ledgerbot", CARDS)
    assert len(threads) == 1 and threads[0] is not threading.main_thread()
