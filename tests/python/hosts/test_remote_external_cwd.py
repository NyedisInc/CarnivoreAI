
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cwd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cwd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.sessions.remote_sessions import resolve_external_cwd  # noqa: E402
from tests.test_hosts_remote_sessions import HOST, rig  # noqa: E402,F401


@pytest.mark.asyncio
async def test_the_far_folder_is_the_far_panes_not_the_far_home(rig) -> None:  # noqa: F811
    far_home = rig.fake.root / "home"
    (far_home / "proj").mkdir()
    remote = await rig.mgr.create_session(session_id="ses_cwd00001", working_dir="~/proj",
                                          auto_start_claude=False, project_name="far cwd", host_key=HOST)
    folder = await resolve_external_cwd(rig.mgr, remote_session_id(HOST, remote.tmux_session))
    assert folder.resolve() == (far_home / "proj").resolve()
