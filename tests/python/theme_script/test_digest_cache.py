
from __future__ import annotations

import hashlib
import json
import os
import time

import pytest

from src.core import theme_script_digest

CALLS = 100



def test_theme_digest_hashes_once_until_the_folder_changes(tmp_path, monkeypatch):
    theme = tmp_path / "neon"
    theme.mkdir()
    (theme / "theme.json").write_text('{"effects": "effects.js"}')
    (theme / "effects.js").write_text("import './helper.js'")
    (theme / "helper.js").write_text("export const a = 1")
    theme_script_digest.invalidate()
    hashed = {"n": 0}
    real = hashlib.new

    def counting(name, *a, **k):
        hashed["n"] += 1
        return real(name, *a, **k)

    monkeypatch.setattr(hashlib, "new", counting)
    monkeypatch.setattr("src.core.skills.digest.hashlib.sha256", lambda *a, **k: (hashed.__setitem__("n", hashed["n"] + 1), real("sha256", *a, **k))[1])
    first = theme_script_digest.digest_effects(theme, "effects.js")
    assert first and len(first) == 64
    hashed["n"] = 0
    start = time.perf_counter()
    for _ in range(CALLS):
        assert theme_script_digest.digest_effects(theme, "effects.js") == first
    per_call_us = (time.perf_counter() - start) / CALLS * 1e6
    print(f"theme digest: {hashed['n']} hashes per {CALLS} calls, {per_call_us:.1f} us per call")
    assert hashed["n"] == 0
    old = (theme / "helper.js").stat()
    (theme / "helper.js").write_text("export const a = 2")
    os.utime(theme / "helper.js", ns=(old.st_atime_ns, old.st_mtime_ns))
    second = theme_script_digest.digest_effects(theme, "effects.js")
    assert second and second != first
    theme_script_digest.invalidate(theme)
    assert theme_script_digest.digest_effects(theme, "effects.js") == second
