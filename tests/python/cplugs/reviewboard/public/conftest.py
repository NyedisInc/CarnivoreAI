
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from src.cplugs.reviewboard.public import assets, routes_owner, wiring
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.write import WRITER
from src.cplugs.reviewboard import public_port
from src.cplugs.sdk import signed_links
from tests.python.cplugs.reviewboard.public.test_public_links_switch_support import set_public
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import Env, make_env


def seeded_dist(root: Path) -> Path:
    dist = root / "dist"
    dist.mkdir()
    (dist / "reviewboard-public.js").write_bytes(b"/* stand-in visitor script */\n")
    (dist / "reviewboard-public.css").write_bytes(b"/* stand-in visitor style */\n")
    return dist


@pytest.fixture
def read_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
    made = make_env(tmp_path)
    monkeypatch.setattr(assets, "DIST_DIR", seeded_dist(tmp_path))
    set_public(made, True)
    public_port.register(made.host.context("reviewboard", background=True))
    make_board(made.root)
    ctx = made.host.context("reviewboard", background=True)
    READER.bind(wiring.build(ctx))
    WRITER.bind(wiring.build_write(ctx))
    yield made
    WRITER.unbind()
    READER.unbind()
    public_port.unregister()


@pytest.fixture
def store(read_env: Env) -> Any:
    return read_env.host.storage("reviewboard")


@pytest.fixture
def folder(read_env: Env) -> Path:
    return read_env.root / SIDECAR["board"]["slug"]
