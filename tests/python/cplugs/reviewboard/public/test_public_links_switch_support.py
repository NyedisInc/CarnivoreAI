
from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from src.cplugs.host import runtime, state as owner_state
from src.api.auth import require_auth
from tests.python.cplugs.reviewboard.harness import Env


def client_for(env: Env) -> TestClient:
    env.app.dependency_overrides[require_auth] = lambda: None
    return TestClient(env.app)


def set_public(env: Env, on: bool, **settings: Any) -> None:
    definition = runtime.find("reviewboard")
    owner_state.update(env.host.state_dir, definition.manifest, None,
                       lambda st: replace(st, settings={**st.settings, "publicLinksEnabled": on, **settings}))
