
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

STALE = re.compile(
    r"submit, hold|hold shift|shift holds|save without telling|shift\+enter in a reply box",
    re.IGNORECASE,
)


def scanned_files() -> list[Path]:
    ask_dir = REPO_ROOT / "web/src/cplugs/huddle/ask"
    ask_sources = [p for p in sorted(ask_dir.rglob("*")) if p.suffix in {".ts", ".svelte"} and not p.name.endswith(".test.ts")]
    return [*sorted((REPO_ROOT / "help/task-manager").glob("*.md")), REPO_ROOT / "features/catalog/task-manager.json", *ask_sources]


def stale_lines(path: Path) -> list[str]:
    rel = path.relative_to(REPO_ROOT)
    return [f"{rel}:{n}: {line.strip()}" for n, line in enumerate(path.read_text().splitlines(), 1) if STALE.search(line)]


def test_scan_reaches_the_surfaces_it_names():
    files = scanned_files()
    names = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    assert "help/task-manager/questions-and-forms.md" in names
    assert "features/catalog/task-manager.json" in names
    assert "web/src/cplugs/huddle/ask/ask-state.svelte.ts" in names
    assert all(p.is_file() for p in files)


def test_pattern_catches_each_old_phrasing():
    for old in (
        "Hold Shift and the key reads **submit, hold**",
        "hold shift on submit to save without telling",
        "the answer saves, then `submitNow` tells the item's list; Shift holds the tell.",
        "Press shift+enter in a reply box or the add box to save it and send a tell",
    ):
        assert STALE.search(old), old


def test_no_reader_facing_surface_teaches_the_shift_hold():
    found = [hit for path in scanned_files() for hit in stale_lines(path)]
    assert found == [], "\n".join(found)
