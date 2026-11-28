
from __future__ import annotations

from pathlib import Path

from src.core.sessions import disposable
from src.models.session_requests import CreateSessionRequest


def test_mint_and_cleanup_managed_scratch_dir(tmp_path: Path):
    minted = disposable.mint_scratch_dir("ses_a1b2c3d4", base_dir=tmp_path)
    p = Path(minted)
    assert p.is_dir()
    assert p.name == "carnivore-scratch-ses_a1b2c3d4"
    assert disposable.is_managed_scratch_dir(minted, base_dir=tmp_path) is True
    assert disposable.cleanup_scratch_dir_best_effort(minted, base_dir=tmp_path) is True
    assert not p.exists()


def test_cleanup_refuses_user_chosen_folders(tmp_path: Path):
    user_dir = tmp_path / "my-real-project"
    user_dir.mkdir()
    nested = tmp_path / "carnivore-scratch-abc" / "sub"
    nested.mkdir(parents=True)

    assert disposable.is_managed_scratch_dir(str(user_dir), base_dir=tmp_path) is False
    assert disposable.cleanup_scratch_dir_best_effort(str(user_dir), base_dir=tmp_path) is False
    assert user_dir.exists()

    assert disposable.is_managed_scratch_dir(str(nested), base_dir=tmp_path) is False
    assert disposable.cleanup_scratch_dir_best_effort(str(nested), base_dir=tmp_path) is False
    assert nested.exists()


def test_create_session_request_accepts_disposable_flag():
    req = CreateSessionRequest(disposable=True, agent_type="claude")
    assert req.disposable is True
    assert CreateSessionRequest().disposable is False
