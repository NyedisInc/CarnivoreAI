
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from src.core.pack.machines import capabilities  # noqa: E402
from tests.python.pack import test_link_peers as lp  # noqa: E402
from tests.python.pack import test_roster_v2 as t2  # noqa: E402


def test_s1_a_crash_between_the_v1_and_v2_issues_leaves_the_link_source_known(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a = pack["a"]
    t2._settle(pack, 2)
    assert a.refresh_roster(lp._inputs()) == "bump:first"
    seen = []
    real = a.custody._issue_roster_v2

    def at_the_crash_point(roster):
        seen.append(a.custody._link_source(a.custody.roster())[0])
        return real(roster)

    monkeypatch.setattr(a.custody, "_issue_roster_v2", at_the_crash_point)
    assert a.refresh_roster(lp._inputs(), link_peers={lp.IDS["b"]: False}) == "bump:authority"
    assert seen == ["known"]
