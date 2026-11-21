
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.mass_death import resume


@pytest.fixture()
def stubs(monkeypatch):
    calls = SimpleNamespace(woken=[], notes=[], answers={})

    async def wake(app_state, session_uuid):
        calls.woken.append(session_uuid)
        answer = calls.answers.get(session_uuid, SimpleNamespace(status="started", tmux_session=f"carnivore_{session_uuid}", code=None))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def schedule(app_state, tmux_name, text):
        calls.notes.append((tmux_name, text))

    monkeypatch.setattr(resume, "_wake", wake)
    monkeypatch.setattr(resume, "_schedule_note", schedule)
    return calls


def test_every_listed_session_is_woken_and_gets_the_note(stubs):
    report = asyncio.run(resume.resume_all(object(), ["a", "b", "c"]))
    assert sorted(stubs.woken) == ["a", "b", "c"]
    assert sorted(n for n, _ in stubs.notes) == ["carnivore_a", "carnivore_b", "carnivore_c"]
    assert {text for _, text in stubs.notes} == {resume.note_text()}
    assert (report.woken, report.refused) == (3, 0)


def test_the_note_text_comes_from_the_catalog_not_the_code():
    assert resume.note_text() != "session.mass_death.note"
    assert "interrupted" in resume.note_text()


def test_a_refused_wake_gets_no_note_and_does_not_stop_the_rest(stubs):
    stubs.answers["b"] = SimpleNamespace(status="refused", tmux_session=None, code="wrapper_needed")
    stubs.answers["c"] = HTTPException(status_code=409, detail="this session is not asleep, so there is nothing to wake")
    report = asyncio.run(resume.resume_all(object(), ["a", "b", "c"]))
    assert [n for n, _ in stubs.notes] == ["carnivore_a"]
    assert (report.woken, report.refused) == (1, 2)
    by_uuid = {o.session_uuid: o for o in report.outcomes}
    assert by_uuid["b"].detail == "wrapper_needed" and "not asleep" in by_uuid["c"].detail


def test_duplicates_are_woken_once_and_the_list_is_bounded(stubs):
    asyncio.run(resume.resume_all(object(), ["a", "a", "b"]))
    assert sorted(stubs.woken) == ["a", "b"]
    with pytest.raises(ValueError):
        asyncio.run(resume.resume_all(object(), [str(i) for i in range(resume.MAX_SESSIONS + 1)]))
