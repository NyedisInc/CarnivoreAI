
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from src.core.federation import mesh_peers  # noqa: E402
from src.core.pack.jobs import boot  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402


def test_s2_a_member_link_reconnect_clears_that_peers_passing_hold_only(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = SimpleNamespace(store=object(), install_id="iid-a")
    monkeypatch.setattr(mesh_peers, "_CONNECT_LISTENERS", [])
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    boot._keep_sync(engine)  # type: ignore[arg-type]
    assert mesh_peers._CONNECT_LISTENERS == []

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    sync = boot._keep_sync(engine)  # type: ignore[arg-type]
    sync._passing_hold[("uid", "iid-c")] = (1, 9999.0)
    sync._passing_hold[("uid", "iid-g")] = (1, 9999.0)
    for listener in list(mesh_peers._CONNECT_LISTENERS):
        listener("iid-c")
    assert ("uid", "iid-c") not in sync._passing_hold and ("uid", "iid-g") in sync._passing_hold
