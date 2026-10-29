from __future__ import annotations

import json

import pytest

from src.core import config_writer
from src.core.deepsearch import rules


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"other": 1}))
    rules._OVERRIDES_CACHE.clear()
    return path


def test_parsed_once_until_the_file_changes(config, monkeypatch):
    reads = []
    real = config_writer.read_config
    monkeypatch.setattr(config_writer, "read_config", lambda p: reads.append(p) or real(p))
    for _ in range(5):
        assert rules.read_overrides(config) == {}
    assert len(reads) == 1
    config.write_text(json.dumps({"other": 2, "pad": "x" * 50}))
    rules.read_overrides(config)
    assert len(reads) == 2


def test_a_write_through_the_writer_is_seen_and_copies_are_private(config):
    assert rules.read_overrides(config) == {}
    written = rules.write_overrides({"families": {"claude": {}}}, config)
    got = rules.read_overrides(config)
    assert got == written
    got["families"] = "mutated"
    assert rules.read_overrides(config) == written


def test_missing_file_reads_empty_and_is_not_cached(tmp_path):
    rules._OVERRIDES_CACHE.clear()
    assert rules.read_overrides(tmp_path / "nope.json") == {}
    assert not rules._OVERRIDES_CACHE
