
from __future__ import annotations

import asyncio
import json

import pytest

from src.api import dev_shape_alerts_routes
from src.config.settings import Settings
from src.core import shape_alert_wiring
from src.core.event_hub import EventHub
from src.core.attention.registry_contract import check_registry_record
from src.core.subagents import shape_alert
from src.models.websocket import WSMessageType

SECRET = "VALUE-SENTINEL-786-toast"


@pytest.fixture(autouse=True)
def _clean():
    shape_alert.reset_for_tests()
    shape_alert.set_listener(None)
    yield
    shape_alert.reset_for_tests()
    shape_alert.set_listener(None)


class _Hub(EventHub):

    def __init__(self) -> None:
        super().__init__()
        self.frames = []

    def publish(self, frame):
        self.frames.append(json.loads(json.dumps(frame)))
        return 1


class _State:
    def __init__(self, hub) -> None:
        self.event_hub = hub


def _broken():
    return check_registry_record({"status": 7314159265358, "sessionId": SECRET})


def test_the_setting_is_typed_and_off_by_default():
    field = Settings.model_fields["dev_shape_alerts"]
    assert field.annotation is bool
    assert field.default is False


def test_off_installs_nothing_and_publishes_nothing():
    hub = _Hub()

    async def run():
        installed = shape_alert_wiring.install(
            _State(hub), asyncio.get_running_loop(), enabled=False)
        shape_alert.report_unrecognized(_broken(), enabled=lambda: False)
        await asyncio.sleep(0)
        return installed

    assert asyncio.run(run()) is False
    assert hub.frames == []


def test_on_publishes_one_names_only_frame_per_new_mismatch_from_any_thread():
    hub = _Hub()

    async def run():
        assert shape_alert_wiring.install(
            _State(hub), asyncio.get_running_loop(), enabled=True)
        for _ in range(3):
            await asyncio.to_thread(
                shape_alert.report_unrecognized, _broken(),
                claude_code_version="2.1.283", enabled=lambda: False)
        await asyncio.sleep(0.01)

    asyncio.run(run())
    assert len(hub.frames) == 1
    frame = hub.frames[0]
    assert frame["type"] == WSMessageType.DEV_SHAPE_UNRECOGNIZED.value == "dev.shape_unrecognized"
    assert frame["file_kind"] == "pid_registry"
    assert "key status is integer" in frame["problems"]
    text = json.dumps(frame)
    assert SECRET not in text and "7314159265358" not in text and "2.1.283" not in text


def test_a_version_that_is_not_digits_and_dots_is_never_repeated(tmp_path):
    assert shape_alert.safe_version("2.1.283") == "2.1.283"
    assert shape_alert.safe_version(SECRET) is None
    assert shape_alert.safe_version(7) is None
    shape_alert.report_unrecognized(_broken(), claude_code_version=SECRET,
                                    enabled=lambda: True, debug_dir=tmp_path)
    note = (tmp_path / shape_alert.NOTE_FILENAME).read_text()
    assert SECRET not in note and "not determinable" in note
    assert shape_alert.recorded()[0]["claude_code_version"] is None


def test_the_route_lists_the_recorded_mismatches_and_every_contract():
    shape_alert.report_unrecognized(_broken(), claude_code_version="2.1.283",
                                    enabled=lambda: False)
    body = asyncio.run(dev_shape_alerts_routes.get_shape_alerts())
    assert body["enabled"] is False
    assert set(body["contracts"]) >= {"pid_registry", "transcript_line", "subagent_meta",
                                      "subagent_jsonl", "timer_call", "timer_result"}
    (alert,) = body["alerts"]
    assert alert["file_kind"] == "pid_registry" and alert["contract_version"] == 1
    assert SECRET not in json.dumps(body)


def test_the_route_is_authenticated():
    from src.api.auth import require_auth

    route = next(r for r in dev_shape_alerts_routes.router.routes
                 if r.path == "/dev/shape-alerts")
    assert any(dep.dependency is require_auth for dep in route.dependencies)
