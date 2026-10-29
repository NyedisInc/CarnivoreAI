
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

import pytest
from fastapi.testclient import TestClient

from scripts.crate.client import CrateClient
from scripts.crate.transport import CHUNK, Body, Response
from src.core.db import connect, db_path_for
from src.cplugs.crate import imports, service
from tests.python.cplugs.crate.api_world import ApiWorld
from tests.python.crate_import.install import Install, make_install

B_INSTALL_ID = "22222222-2222-4222-8222-222222222222"
A, B = "a", "b"


class WorldTransport:

    def __init__(self, harness: "TwoInstalls", which: str) -> None:
        self.harness, self.which = harness, which
        self.calls = 0

    def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None, length: Optional[int] = None) -> Response:
        self.harness.activate(self.which)
        self.calls += 1
        content: Any = body
        if body is not None and not isinstance(body, bytes):
            content = iter(lambda: body.read(CHUNK), b"")
        reply = self.harness.clients[self.which].request(method, path, headers=dict(headers), content=content)

        def chunks() -> Iterator[bytes]:
            data = reply.content
            for start in range(0, len(data), CHUNK):
                yield data[start:start + CHUNK]

        return Response(reply.status_code, {k.lower(): v for k, v in reply.headers.items()}, chunks())


class TwoInstalls:

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, authed: bool = True) -> None:
        for name in ("a", "b", "binst"):
            (tmp_path / name).mkdir()
        self.a = ApiWorld(tmp_path / "a", monkeypatch)
        self.b = ApiWorld(tmp_path / "b", monkeypatch)
        self.install: Install = make_install(tmp_path / "binst", install_id=B_INSTALL_ID)
        self.b.world.state = self.install.state
        self.apis: Dict[str, ApiWorld] = {A: self.a, B: self.b}
        self.clients: Dict[str, TestClient] = {A: self.a.client(authed=authed), B: self.b.client(authed=authed)}
        self._real_import_env = imports.import_env_of
        self.active = A
        monkeypatch.setattr(service, "env_of", lambda ctx: self.apis[self.active].env)
        monkeypatch.setattr(imports, "import_env_of", self._import_env)
        self.transports = {A: WorldTransport(self, A), B: WorldTransport(self, B)}
        self.client_a = CrateClient(transport=self.transports[A], poll_interval=0.02)
        self.client_b = CrateClient(transport=self.transports[B], poll_interval=0.02)

    def activate(self, which: str) -> None:
        self.active = which

    def _import_env(self, env: Any) -> Any:
        return self.install.env if self.active == B else self._real_import_env(env)

    def b_counts(self) -> Dict[str, int]:
        with closing(connect(db_path_for(self.install.state), create=False)) as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("sessions", "projects")}
