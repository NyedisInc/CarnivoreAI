
from __future__ import annotations

import src.main  # noqa: F401
from src.api.launch_profile_errors import gone_profile_error
from src.core.hosts.registry import HostUnavailable
from src.core.launch_profiles.resolve import LaunchProfileNotFound

from .conftest import LEAK, assert_fixed


class _HostDown:

    async def create_session(self, **_kwargs):
        raise HostUnavailable("host_unreachable", f"cannot reach {LEAK}")


def test_a_down_host_answers_its_code_without_the_text(driver):
    response, events = driver.call("POST", "/sessions", _HostDown(), json={"host": "other"})
    if response.status_code == 422:
        raise AssertionError("request shape changed: " + response.text)
    assert_fixed(response, 502, "host_unreachable", events)


def test_a_gone_profile_keeps_the_id_and_the_picks_but_not_the_text():
    exc = LaunchProfileNotFound(f"p-{LEAK}")
    caught = gone_profile_error(exc, ["claude", "codex"])
    detail = caught.detail
    assert caught.status_code == 400 and detail["code"] == "wrapper_needed"
    assert detail["codes"] == ["wrapper_needed", "launch_profile_needed"] and detail["wrapper_options"] == ["claude", "codex"]
    assert detail["profile"] == f"p-{LEAK}" and "does not exist" not in detail["detail"]
