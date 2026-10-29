import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = [REPO / "client" / "js", REPO / "web" / "src"]
SUFFIXES = {".js", ".mjs", ".ts", ".svelte"}
USE = re.compile(r"\bnew\s+(?:window\.|globalThis\.)?IntersectionObserver\b|(?<![\w.])IntersectionObserver\s*\(")
KNOWN_OBSERVERS = ["web/src/lib/widgets-page/PlaceDock.svelte"]
COMMENT = re.compile(r"^\s*(?://|/\*|\*)")


def offenders(files, *, root: Path = REPO):
    found = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if ".test." in path.name or "/fixtures/" in rel:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if USE.search(line) and not COMMENT.match(line):
                found.append(f"{rel}:{number}")
    return found


def production_files():
    return [p for root in ROOTS for p in root.rglob("*") if p.suffix in SUFFIXES and p.is_file()]


def test_scanner_can_go_red(tmp_path: Path) -> None:
    planted = tmp_path / "client" / "js" / "planted.js"
    planted.parent.mkdir(parents=True)
    planted.write_text("const o = new IntersectionObserver(() => {});\n", encoding="utf-8")
    assert offenders([planted], root=tmp_path) == ["client/js/planted.js:1"]


def test_no_real_intersection_observer_in_production_code():
    files = production_files()
    assert len(files) > 200, "the scan looked at almost nothing"
    assert [o for o in offenders(files) if o.rsplit(":", 1)[0] not in KNOWN_OBSERVERS] == []
