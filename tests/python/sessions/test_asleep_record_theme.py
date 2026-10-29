
import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_at_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_at_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api.session_record_payload import _session_record_payload
from src.core.sessions.theme_store import ThemeStore


def _row(lifecycle: str, source: str, work: str) -> dict:
    return {"id": 4, "session_uuid": "u", "origin": "created", "tmux_name": "cloude_demo",
            "tmux_created_epoch": 1, "project_attribution": "x", "archived_at": None,
            "lifecycle": lifecycle, "lifecycle_source": source, "working_dir": work}


def test_an_asleep_record_wears_its_pin_else_its_project_theme(tmp_path):
    work = tmp_path / "proj"
    work.mkdir()
    themes = ThemeStore(pin_path=lambda: tmp_path / "pinned_themes.json")
    asleep = _row("stopped", "slept_by_user", str(work))
    assert _session_record_payload(asleep, None, themes).pinned_theme is None, "nothing held: not measured"
    themes.set_project_theme(work, "snes")
    assert _session_record_payload(asleep, None, themes).pinned_theme == "snes"
    themes.set_pin("cloude_demo", "alien")
    assert _session_record_payload(asleep, None, themes).pinned_theme == "alien"
    assert _session_record_payload(asleep).pinned_theme is None, "no store: not measured"
    running = _row("running", "tmux_list", str(work))
    assert _session_record_payload(running, None, themes).pinned_theme is None
