from __future__ import annotations

import json

from scripts.design import thin_error_logs as guard

THIN = 'def f(e):\n    logger.error("boom", error=str(e))\n'
FAT = 'def f(e):\n    logger.error("boom", error=str(e), error_type=type(e).__name__, exc_info=True)\n'
KNOWN_LANE_PREFIXES = ("src/api/provider_",)


def test_thin_call_is_counted_and_a_fat_one_is_not() -> None:
    assert guard.count_thin(THIN) == 1
    assert guard.count_thin(FAT) == 0
    assert guard.count_thin('log.error("x", error=str(exc))') == 1
    assert guard.count_thin('logger.warning("x", error=str(exc))') == 0


def test_over_baseline_flags_an_unlisted_file(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(THIN)
    counts = guard.scan(tmp_path / "src", tmp_path)
    assert counts == {"src/m.py": 1}
    assert guard.over_baseline(counts, {}) == ["src/m.py: 1 > 0"]
    assert guard.over_baseline(counts, {"src/m.py": 1}) == []
    assert guard.stale_known(counts, {"src/m.py": 2}) == ["src/m.py: baseline 2, found 1"]


def test_src_holds_the_baseline() -> None:
    baseline = json.loads(guard.BASELINE.read_text(encoding="utf-8"))
    counts = guard.scan()
    assert guard.over_baseline(counts, baseline) == []
    assert guard.stale_known(counts, baseline) == []
    assert all(path.startswith(KNOWN_LANE_PREFIXES) for path in baseline), "KNOWN holds only the lanes the sweep skipped"


def test_guard_is_wired_into_the_commit_gate() -> None:
    hook = (guard.REPO / "scripts" / "hooks" / "pre-commit-secret-scan.sh").read_text(encoding="utf-8")
    assert "scripts/design/thin_error_logs.py" in hook


def test_scan_staged_reads_the_index_not_the_work_tree(tmp_path, monkeypatch) -> None:
    import os
    import subprocess

    for name in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(name)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "src").mkdir()
    staged_file = tmp_path / "src" / "a b.py"
    staged_file.write_text(THIN)
    git("add", "src/a b.py")
    staged_file.write_text(FAT)
    (tmp_path / "src" / "scratch.py").write_text(THIN)
    assert guard.scan_staged(tmp_path) == {"src/a b.py": 1}
