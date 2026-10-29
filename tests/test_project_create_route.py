
import asyncio
import os
import tempfile
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pcr_wd_"))
os.environ.setdefault("TOTP_SECRET", "pcrsecretnotreal")
os.environ.setdefault("JWT_SECRET", "pcrjwtnotreal")


class _RecordingManager:

    def __init__(self):
        self.calls = []

    async def create_session(self, **kwargs):
        from src.models import Session

        self.calls.append(kwargs)
        return Session(
            id=kwargs.get("session_id") or "ses_test",
            working_dir=kwargs.get("working_dir") or "/tmp/cc-old-client",
        )


def _post(body):
    from src.api.auth import require_auth
    from src.main import app

    manager = _RecordingManager()
    previous = getattr(app.state, "session_manager", None)
    app.state.session_manager = manager
    app.dependency_overrides[require_auth] = lambda: True

    async def _drive():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pcr.local/api/v1"
        ) as client:
            return await client.post("/sessions", json=body)

    try:
        response = asyncio.run(_drive())
    finally:
        app.dependency_overrides.pop(require_auth, None)
        app.state.session_manager = previous
    return response, manager


def _pin_roots(monkeypatch, home: Path):
    from src.core import project_directory

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        project_directory, "projects_root", lambda settings=None: str(home)
    )


@pytest.fixture()
def home_parent(tmp_path, monkeypatch):
    parent = tmp_path / "Development"
    parent.mkdir()
    _pin_roots(monkeypatch, tmp_path)
    return parent


def test_a_chosen_folder_becomes_the_working_dir_as_is(home_parent):
    chosen = home_parent / "Cobalt-Deck"
    response, manager = _post(
        {
            "project_name": "Cobalt-Deck",
            "project_parent_dir": str(chosen),
            "auto_start_claude": True,
        }
    )
    assert response.status_code == 201, response.text
    assert len(manager.calls) == 1
    working_dir = manager.calls[0]["working_dir"]
    assert working_dir == str(Path(os.path.realpath(chosen)))
    assert "ses_" not in Path(working_dir).name
    assert Path(working_dir).is_dir()


def test_picking_an_existing_folder_uses_it_directly_with_no_subfolder(home_parent):
    response, manager = _post(
        {
            "project_name": "Punchlist Test",
            "project_parent_dir": str(home_parent),
            "auto_start_claude": True,
        }
    )
    assert response.status_code == 201, response.text
    working_dir = manager.calls[0]["working_dir"]
    assert working_dir == str(Path(os.path.realpath(home_parent)))
    assert not working_dir.endswith("/Punchlist Test")


def test_a_symlinked_folder_reaches_the_manager_in_the_long_spelling(
    tmp_path, monkeypatch
):
    real_parent = tmp_path / "iCloud" / "Sync" / "Development"
    real_parent.mkdir(parents=True)
    link = tmp_path / "Development"
    link.symlink_to(real_parent, target_is_directory=True)
    _pin_roots(monkeypatch, tmp_path)

    response, manager = _post(
        {"project_name": "Long Spelling", "project_parent_dir": str(link / "Long Spelling")}
    )
    assert response.status_code == 201, response.text
    assert manager.calls[0]["working_dir"] == str(real_parent / "Long Spelling")


@pytest.mark.parametrize(
    "name",
    ["a/b", "..", ".hidden", ""],
)
def test_an_illegal_name_is_a_400_and_creates_nothing(home_parent, name):
    response, manager = _post(
        {"project_name": name, "project_parent_dir": str(home_parent)}
    )
    assert response.status_code == 400, response.text
    assert manager.calls == []
    assert list(home_parent.iterdir()) == []


def test_a_parent_outside_the_roots_is_a_400(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _pin_roots(monkeypatch, home)

    response, manager = _post(
        {"project_name": "Sneaky", "project_parent_dir": str(outside)}
    )
    assert response.status_code == 400, response.text
    assert "outside" in response.json()["detail"]
    assert manager.calls == []


def test_traversal_is_a_400(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    _pin_roots(monkeypatch, home)

    response, manager = _post(
        {
            "project_name": "Sneaky",
            "project_parent_dir": str(home / ".." / ".." / ".." / "etc"),
        }
    )
    assert response.status_code == 400, response.text
    assert manager.calls == []


def test_a_non_empty_existing_directory_is_accepted(home_parent):
    taken = home_parent / "Taken"
    taken.mkdir()
    (taken / "file.txt").write_text("hello")

    response, manager = _post(
        {"project_name": "Taken", "project_parent_dir": str(taken)}
    )
    assert response.status_code == 201, response.text
    assert manager.calls[0]["working_dir"] == str(taken)


def test_an_existing_empty_directory_is_accepted(home_parent):
    (home_parent / "Empty").mkdir()
    response, manager = _post(
        {"project_name": "Empty", "project_parent_dir": str(home_parent / "Empty")}
    )
    assert response.status_code == 201, response.text
    assert manager.calls[0]["working_dir"].endswith("/Empty")


def test_a_refusal_is_a_400_not_a_wrapped_500(home_parent):
    response, _manager = _post(
        {"project_name": "a/b", "project_parent_dir": str(home_parent)}
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Failed to create session" not in detail
    assert "cannot contain" in detail


def test_an_old_client_sending_neither_field_still_works(home_parent):
    response, manager = _post({"project_name": "Old Client"})
    assert response.status_code == 201, response.text
    assert len(manager.calls) == 1
    assert manager.calls[0]["working_dir"] is None


def test_the_fallback_branch_still_generates_and_now_warns():
    source = Path("src/core/session_manager.py").read_text(encoding="utf-8")
    marker = "work_path = settings.get_working_dir() / session_id"
    assert marker in source, "the fallback branch moved; re-point this test"
    after = source.split(marker, 1)[1][:600]
    assert "logger.warning" in after
    assert "session_working_dir_fallback_generated" in after
