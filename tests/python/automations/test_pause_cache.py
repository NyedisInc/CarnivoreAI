
from __future__ import annotations

import json
import os
from pathlib import Path

from src.core import config_writer
from src.core.automations import pause


def test_repeated_reads_parse_once_and_a_change_is_seen(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"automations_paused": False}))
    pause._cache.clear()
    parses: list[int] = []
    real = config_writer.read_config

    def counting(path: Path):
        parses.append(1)
        return real(path)

    monkeypatch.setattr(config_writer, "read_config", counting)
    assert [pause.is_paused(cfg) for _ in range(10)] == [False] * 10
    assert len(parses) == 1
    cfg.write_text(json.dumps({"automations_paused": True, "pad": "x"}))
    os.utime(cfg, ns=(1, 1))
    assert pause.is_paused(cfg) is True
    pause.set_paused(False, cfg)
    assert pause.is_paused(cfg) is False
