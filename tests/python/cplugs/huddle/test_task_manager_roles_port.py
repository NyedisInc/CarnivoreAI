
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.api import session_roles_listing
from src.core.federation import peer_listing
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_roles import read as roles_read
from src.cplugs.huddle import schedule_port
from src.cplugs.huddle.roles import lead, port as roles_port
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import ports
from src.cplugs.sdk.ownership import CONTRIBUTION_SEAMS
from src.models import SessionInfo
from tests.python.cplugs.huddle.roles_rig import aged, give_asleep
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env  # noqa: F401


def info(session_id: str, **fields) -> SessionInfo:
    base = {"session": {"id": session_id, "working_dir": "/tmp", "agent_type": "claude"}, "tmux_session": f"cloude_{session_id}",
            "host_key": LOCAL_HOST_KEY, "project_id": 12}
    return SessionInfo.model_validate({**base, **fields})


def stamp(rows) -> None:
    asyncio.run(session_roles_listing.mark_session_roles(object(), rows))


def test_the_fields_default_to_null_on_the_wrapper_and_not_on_the_session():
    row = info("ses_1")
    assert row.task_lead is None and row.do_not_disturb is None and not hasattr(row.session, "task_lead")


def test_with_the_plugin_off_there_is_no_port_and_every_row_is_null():
    ports.unregister(roles_read.PORT)
    assert asyncio.run(roles_read.read(object(), [info("ses_1")])) is None
    row = info("ses_1")
    row.task_lead = row.do_not_disturb = True
    stamp([row])
    assert row.task_lead is None and row.do_not_disturb is None


class FakePort:

    def __init__(self, answer=None, fail=None) -> None:
        self.answer, self.fail, self.seen = answer or {}, fail, []

    async def read(self, app_state, infos):
        self.seen.append([i.session.id for i in infos])
        if self.fail:
            raise self.fail
        return self.answer


@pytest.fixture
def fake_port():
    def make(**kwargs) -> FakePort:
        fake = FakePort(**kwargs)
        ports.register(roles_read.PORT, fake)
        return fake

    yield make
    ports.unregister(roles_read.PORT)


def test_a_port_that_works_stamps_booleans_and_a_row_it_does_not_name_stays_null(fake_port):
    fake = fake_port(answer={"ses_1": {"lead": True, "dnd": False}, "ses_2": {"lead": False, "dnd": True}})
    rows = [info("ses_1"), info("ses_2"), info("ses_3")]
    stamp(rows)
    assert [(r.task_lead, r.do_not_disturb) for r in rows] == [(True, False), (False, True), (None, None)]
    assert fake.seen == [["ses_1", "ses_2", "ses_3"]]


@pytest.mark.parametrize("error", [OSError("disk"), RuntimeError("x"), ValueError("y"), LookupError("z")])
def test_a_port_that_fails_makes_every_row_null_never_false(fake_port, error):
    fake_port(fail=error)
    row = info("ses_1")
    row.task_lead = True
    stamp([row])
    assert row.task_lead is None and row.do_not_disturb is None


def test_a_paired_computers_row_is_never_asked_about_and_stays_null(fake_port):
    fake = fake_port(answer={"ses_1": {"lead": True, "dnd": True}})
    remote = info("remote:peer-1:ses_9", host_key="peer-1")
    mine = info("ses_1")
    stamp([mine, remote])
    assert remote.task_lead is None and mine.task_lead is True and fake.seen == [["ses_1"]]
    assert {"task_lead", "do_not_disturb"} <= set(peer_listing._UNMEASURED)


def test_the_seam_is_declared_and_the_huddle_owns_it():
    manifest = json.loads((Path(roles_port.__file__).parents[1] / "cplug.json").read_text(encoding="utf-8"))
    assert "session.roles" in CONTRIBUTION_SEAMS and "session.roles" in manifest["owns"]["contributions"]
    assert roles_port.NAME == roles_read.PORT == "session.roles" and schedule_port.NAME == "session.schedules"


def test_the_real_port_answers_the_star_and_the_badge_per_live_row(env, monkeypatch):
    give_asleep(monkeypatch, [])
    env.set_rows([aged("ses_old", 12, 5), aged("ses_new", 12, 1), aged("ses_other", 99, 3)])
    RoleStore(env.store).set_dnd("ses_new", True)
    real = roles_port.RolesPort(env.ctx)
    rows = asyncio.run(env.app.state.session_manager.list_session_infos())
    got = asyncio.run(real.read(object(), rows))
    assert got == {"ses_old": {"lead": True, "dnd": False}, "ses_new": {"lead": False, "dnd": True}, "ses_other": {"lead": True, "dnd": False}}
    assert RoleStore(env.store).seat("12").lead_by == ""
    asyncio.run(real.settle())
    assert RoleStore(env.store).seat("12").lead_by == lead.BY_AUTO
    assert asyncio.run(real.read(object(), rows)) == got


def test_a_role_write_wakes_the_listing_only_once_the_listing_has_handed_over_the_app(env, monkeypatch):
    woken = []
    app_state = type("State", (), {"listing_publisher": type("P", (), {"wake": lambda self: woken.append(1)})()})()
    real = roles_port.RolesPort(env.ctx)
    real.wake()
    assert woken == []
    give_asleep(monkeypatch, [])
    asyncio.run(real.read(app_state, asyncio.run(env.app.state.session_manager.list_session_infos())))
    real.wake()
    assert woken == [1]
