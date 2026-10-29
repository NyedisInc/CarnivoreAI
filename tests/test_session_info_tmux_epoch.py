
from __future__ import annotations

from tests.test_dead_pane_not_running import _register, _row, mgr  # noqa: F401
from src.core.session_status import STATUS_IDLE


def test_a_listed_session_carries_its_measured_epoch(mgr, tmp_path):  # noqa: F811
    _register(mgr, "real", "cloude_ses_real", tmp_path)
    info = mgr._session_info_for("real", status_map=_row("cloude_ses_real", STATUS_IDLE))
    assert info is not None
    assert info.session.tmux_created_epoch == 1755000000
    assert "tmux_created_epoch" not in type(info).model_fields
    assert mgr._registry.sessions["real"].tmux_created_epoch is None


def test_a_reused_name_reads_the_new_instance_epoch(mgr, tmp_path):  # noqa: F811
    _register(mgr, "real", "cloude_ses_real", tmp_path)
    row = _row("cloude_ses_real", STATUS_IDLE)
    row["cloude_ses_real"]["created_at_epoch"] = 1755009999
    info = mgr._session_info_for("real", status_map=row)
    assert info is not None
    assert info.session.tmux_created_epoch == 1755009999


def test_an_unmeasured_epoch_is_none(mgr, tmp_path):  # noqa: F811
    _register(mgr, "murky", "cloude_ses_murky", tmp_path)
    info = mgr._session_info_for("murky", status_map={})
    assert info is not None
    assert info.session.tmux_created_epoch is None
