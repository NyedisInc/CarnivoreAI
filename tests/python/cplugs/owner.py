
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from src.cplugs.host import runtime, state as owner_state


def turn_on(host: runtime.Host, cplug_id: str = "huddle") -> owner_state.CplugState:
    d = runtime.find(cplug_id)
    assert d is not None, cplug_id
    return owner_state.update(host.state_dir, d.manifest, None,
                              lambda st: replace(st, enabled=True, grants=tuple(d.manifest.permissions)))


def isolated_host(monkeypatch: Any, app: Any, state_dir: Path, on: Iterable[str] = ("huddle",)) -> runtime.Host:
    host = runtime.Host(state_dir, app, publish=lambda topic: None)
    monkeypatch.setattr(app.state, "cplugs_host", host, raising=False)
    monkeypatch.setattr(runtime, "_host", host)
    for cplug_id in on:
        turn_on(host, cplug_id)
    return host
