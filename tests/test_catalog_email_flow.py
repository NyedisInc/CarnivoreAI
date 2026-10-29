
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cef_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cef_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.email_flow import MAX_PENDING_FLOWS, EmailFlowStore
from src.models.catalog_signin import provider_of_login


class FakeClock:

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestWhatTheHandleHidesAndWhatItYields:

    def test_a_started_flow_yields_the_address_and_the_session(self):
        flows = EmailFlowStore(clock=FakeClock())
        flow_id = flows.start(
            email="ada@example.test", session="SESSION-SECRET", expires_in=900
        )
        pending = flows.pending_for(flow_id)
        assert pending is not None
        assert pending.email == "ada@example.test"
        assert pending.session == "SESSION-SECRET"

    def test_two_flows_never_share_a_handle(self):
        flows = EmailFlowStore(clock=FakeClock())
        first = flows.start(email="a@example.test", session="ONE")
        second = flows.start(email="b@example.test", session="TWO")
        assert first != second
        assert flows.pending_for(first).session == "ONE"
        assert flows.pending_for(second).session == "TWO"

    def test_an_unknown_handle_yields_nothing(self):
        flows = EmailFlowStore(clock=FakeClock())
        flows.start(email="a@example.test", session="ONE")
        assert flows.pending_for("not-a-real-flow") is None


class TestAFlowStopsBeingUsable:

    def test_it_expires_on_the_second_it_says_it_will(self):
        clock = FakeClock()
        flows = EmailFlowStore(clock=clock)
        flow_id = flows.start(email="a@example.test", session="ONE", expires_in=900)
        clock.advance(899)
        assert flows.pending_for(flow_id) is not None
        clock.advance(1)
        assert flows.pending_for(flow_id) is None

    def test_finishing_forgets_it(self):
        flows = EmailFlowStore(clock=FakeClock())
        flow_id = flows.start(email="a@example.test", session="ONE")
        flows.finish(flow_id)
        assert flows.pending_for(flow_id) is None

    def test_finishing_twice_is_not_an_error(self):
        flows = EmailFlowStore(clock=FakeClock())
        flow_id = flows.start(email="a@example.test", session="ONE")
        flows.finish(flow_id)
        flows.finish(flow_id)
        assert flows.pending_for(flow_id) is None

    def test_an_expired_entry_is_really_dropped_not_merely_hidden(self):
        clock = FakeClock()
        flows = EmailFlowStore(clock=clock)
        for index in range(4):
            flows.start(email=f"a{index}@example.test", session="ONE", expires_in=900)
        clock.advance(901)
        assert flows.pending_for("anything") is None
        assert len(flows._flows) == 0


class TestTheStoreIsBounded:

    def test_the_ninth_start_evicts_the_oldest(self):
        clock = FakeClock()
        flows = EmailFlowStore(clock=clock)
        ids = []
        for index in range(MAX_PENDING_FLOWS):
            ids.append(
                flows.start(email=f"a{index}@example.test", session=f"S{index}")
            )
            clock.advance(1)
        assert len(flows._flows) == MAX_PENDING_FLOWS
        newest = flows.start(email="last@example.test", session="LAST")
        assert len(flows._flows) == MAX_PENDING_FLOWS
        assert flows.pending_for(ids[0]) is None
        assert flows.pending_for(ids[1]) is not None
        assert flows.pending_for(newest) is not None

    def test_a_restart_drops_every_pending_flow(self):
        clock = FakeClock()
        first = EmailFlowStore(clock=clock)
        flow_id = first.start(email="a@example.test", session="ONE")
        second = EmailFlowStore(clock=clock)
        assert second.pending_for(flow_id) is None


class TestWhichProviderAStoredLoginCameFrom:

    def test_an_address_is_the_email_provider(self):
        assert provider_of_login("ada@example.test") == "email"

    def test_a_handle_is_the_github_provider(self):
        assert provider_of_login("acme") == "github"

    def test_nobody_named_is_no_provider_at_all(self):
        assert provider_of_login(None) is None
        assert provider_of_login("") is None
