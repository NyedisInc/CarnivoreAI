
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from src.cplugs.publicboard import routes_owner, wiring
from src.cplugs.publicboard.read import READER
from src.cplugs.reviewboard import public_port
from src.cplugs.sdk import signed_links
from tests.python.cplugs.owner import turn_on
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import Env, make_env


@pytest.fixture
def read_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
    made = make_env(tmp_path)
    turn_on(made.host, "publicboard")
    made.app.include_router(routes_owner.router, prefix="/api/v1")
    public_port.register(made.host.context("reviewboard", background=True))
    make_board(made.root)
    READER.bind(wiring.build(SimpleNamespace(storage=made.host.storage("publicboard"))))
    yield made
    READER.unbind()
    public_port.unregister()


@pytest.fixture
def store(read_env: Env) -> Any:
    return read_env.host.storage("publicboard")


@pytest.fixture
def folder(read_env: Env) -> Path:
    return read_env.root / SIDECAR["board"]["slug"]
