
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.core.companies import hero_art_gen, hero_images

CALLS = 100


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CARNIVORE_STATE_DIR", str(tmp_path))
    return tmp_path


def test_fail_note_read_once_until_a_writer_runs(state_dir, monkeypatch):
    reads = {"n": 0}
    real = Path.read_text

    def counting(self, *a, **k):
        if self.name.endswith(".fail.json"):
            reads["n"] += 1
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", counting)
    hero_art_gen._failed(hero_images.COMPANY, 7, 0.0, "boom")
    reads["n"] = 0
    start = time.perf_counter()
    for _ in range(CALLS):
        assert hero_art_gen._read_fail(hero_images.COMPANY, 7)["attempts"] == 1
    per_call_us = (time.perf_counter() - start) / CALLS * 1e6
    print(f"fail note: {reads['n']} reads per {CALLS} calls, {per_call_us:.1f} us per call")
    assert reads["n"] == 1
    hero_art_gen._failed(hero_images.COMPANY, 7, 0.0, "boom again")
    assert hero_art_gen._read_fail(hero_images.COMPANY, 7)["attempts"] == 2
    hero_images.remove(hero_images.COMPANY, 7)
    assert hero_art_gen._read_fail(hero_images.COMPANY, 7) == {}
    note = hero_images.fail_note_path(hero_images.COMPANY, 8)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(json.dumps({"attempts": 1}))
    assert hero_art_gen._read_fail(hero_images.COMPANY, 8)["attempts"] == 1
    note.write_text(json.dumps({"attempts": 3}))
    assert hero_art_gen._read_fail(hero_images.COMPANY, 8)["attempts"] == 3


