
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_global_routes as routes  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for, set_meta  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.db_models import META_INSTALL_ID  # noqa: E402
from src.core.federation import fed_key, grants, peer_token  # noqa: E402
from src.core.pack.globalsync import sender  # noqa: E402
from src.core.pack.machines import config_state, restrictions  # noqa: E402
from src.core.pack.transport import blobs  # noqa: E402
from tests.python.pack.globalsync.test_global_sync_core import build, make_home  # noqa: E402

RECEIVER_IID, MAIN_IID = "iid-receiver", "iid-main"


class Rig:

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.state, self.home = tmp / "state", tmp / "receiver"
        self.state.mkdir()
        (self.home / ".claude").mkdir(parents=True)
        assert ensure_db_migrated(self.state).status == "ok"
        self.opt_in = True
        with closing(connect(db_path_for(self.state), create=False)) as conn:
            set_meta(conn, META_INSTALL_ID, RECEIVER_IID)
            key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
            self.grant = grants.create_grant(conn, peer_install_id=MAIN_IID, public_key=key, label="main", scopes=("global-setup",))
        self.token = peer_token.mint(self.grant, RECEIVER_IID)[0]
        self.main_home = make_home(tmp, "main")
        self.bundle = build(self.main_home, tmp / "bundle.tgz")
        monkeypatch.setattr(type(settings), "get_state_dir", lambda s, state=self.state: state, raising=True)
        monkeypatch.setattr(routes, "state_dir", lambda: self.state)
        monkeypatch.setattr(routes, "home_dir", lambda: self.home)
        monkeypatch.setattr(routes, "local_accounts", lambda: [])
        monkeypatch.setattr(routes, "held_alpha", lambda: MAIN_IID)
        monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
        monkeypatch.setattr(config_state, "default", lambda: type("S", (), {"restrictions": lambda s: restrictions.Restrictions(
            may_receive_global_setup=self.opt_in)})())
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/v1")
        self.client = TestClient(app)

    def auth(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {self.token if token is None else token}"}

    def push(self, headers: dict):
        data = self.bundle.path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        blob_id = blobs.new_id()
        base = f"/api/v1{sender.BLOBS_PATH}/{blob_id}"
        put = self.client.put(f"{base}?offset=0", content=data, headers={**headers, "X-Chunk-Sha256": sha})
        if put.status_code != 200:
            return put, None
        seal = self.client.post(f"{base}/seal", headers=headers, json={"size": len(data), "sha256": sha, "kind": "tar"})
        assert seal.status_code == 200, seal.text
        body = {"blob_id": blob_id, "blob_sha256": sha, "digest": self.bundle.digest, "harnesses": ["claude", "codex"]}
        return put, self.client.post(f"/api/v1{sender.APPLY_PATH}", headers=headers, json=body)


@pytest.fixture()
def rig(tmp_path, monkeypatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


def test_valid_peer_token_lands_files_in_the_receivers_home_with_its_own_paths(rig: Rig) -> None:
    _, applied = rig.push(rig.auth())
    assert applied is not None and applied.status_code == 200, applied.text if applied is not None else ""
    assert applied.json()["report"]["written"] > 0
    claude = rig.home / ".claude"
    assert (claude / "hooks" / "pre.sh").exists() and (claude / "CLAUDE.md").read_text() == "# rules\n"
    for rel in ("skills/demo/SKILL.md", "statusline-command.sh", "settings.json", "plugins/installed_plugins.json"):
        text = (claude / rel).read_text()
        assert str(rig.main_home) not in text and str(rig.home) in text, rel
    assert json.loads((claude / "settings.json").read_text())["statusLine"]["command"] == f"{rig.home}/.claude/statusline-command.sh"
    assert not (claude / ".credentials.json").exists()
    assert list((rig.state / "pack" / "global-inbox").iterdir()) == []


@pytest.mark.parametrize("token", ["", "garbage", "eyJhbGciOiJIUzI1NiJ9.e30.x"])
def test_missing_or_wrong_token_is_refused_and_nothing_lands(rig: Rig, token: str) -> None:
    headers = {} if token == "" else rig.auth(token)
    put, applied = rig.push(headers)
    assert put.status_code == 401 and applied is None
    assert list((rig.home / ".claude").iterdir()) == []


def test_a_peer_that_is_not_the_held_alpha_is_refused(rig: Rig, monkeypatch) -> None:
    monkeypatch.setattr(routes, "held_alpha", lambda: "someone-else")
    put, applied = rig.push(rig.auth())
    assert put.status_code == 403 and put.json()["detail"]["code"] == "not_alpha" and applied is None


def test_receiver_opt_in_off_refuses_and_nothing_lands(rig: Rig) -> None:
    rig.opt_in = False
    put, applied = rig.push(rig.auth())
    assert put.status_code == 403 and put.json()["detail"]["code"] == "pack_restricted" and applied is None
    assert list((rig.home / ".claude").iterdir()) == []


def test_real_opt_in_off_drops_the_scope_and_the_refusal_names_the_rule(rig: Rig) -> None:
    rig.opt_in = False
    with closing(connect(db_path_for(rig.state), create=False)) as conn:
        assert grants.set_scopes(conn, rig.grant.grant_id, ("machine",))
    put, applied = rig.push(rig.auth())
    assert put.status_code == 403 and put.json()["detail"]["rule"] == "may_receive_global_setup" and applied is None
