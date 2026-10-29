
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DOCS_DIR = REPO_ROOT / "docs"
INDEX_MD = DOCS_DIR / "INDEX.md"
INDEX_REF = "docs/INDEX.md"


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path} not found, nothing to check")
    return path.read_text(encoding="utf-8", errors="replace")


def _index_text() -> str:
    return _read(INDEX_MD)


def _docs_markdown_files() -> list[Path]:
    if not DOCS_DIR.is_dir():
        pytest.skip(f"docs/ not found at {DOCS_DIR}, nothing to check")
    return sorted(p for p in DOCS_DIR.glob("*.md") if p.name != INDEX_MD.name)


def test_every_docs_file_is_named_in_the_index() -> None:
    text = _index_text()
    docs = _docs_markdown_files()
    assert docs, "docs/ holds no markdown files, which is not an expected state"

    missing = [
        f"docs/{path.name}"
        for path in docs
        if f"docs/{path.name}" not in text
    ]

    assert not missing, (
        "These files in docs/ are not named in docs/INDEX.md, so a "
        "clean-context agent cannot find them:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a row for each to the table in docs/INDEX.md, with one "
        "line saying WHEN to read it. A filename alone is not a routing entry. "
        "Do not delete or move the document to make this pass."
    )


def test_every_warez_doc_is_named_in_the_index() -> None:
    text = _index_text()
    warez_dir = DOCS_DIR / "warez"
    if not warez_dir.is_dir():
        pytest.skip(f"{warez_dir} not found, nothing to check")
    missing = [f"docs/warez/{p.name}" for p in sorted(warez_dir.glob("*.md")) if f"docs/warez/{p.name}" not in text]
    assert not missing, "docs/warez files not named in docs/INDEX.md:\n  " + "\n  ".join(missing)


def test_the_index_does_not_route_to_documents_that_are_gone() -> None:
    wildcard_chars = set("*?[]<>")
    text = _index_text()
    docs = _docs_markdown_files()
    on_disk = {f"docs/{path.name}" for path in docs} | {INDEX_REF}

    referenced: set[str] = set()
    for token in text.replace("`", " ").replace("(", " ").replace(")", " ").split():
        cleaned = token.strip(".,:;\"'|")
        if wildcard_chars & set(cleaned):
            continue
        if cleaned.startswith("docs/") and cleaned.endswith(".md"):
            if cleaned.count("/") == 1:
                referenced.add(cleaned)

    dangling = sorted(referenced - on_disk)

    assert not dangling, (
        "docs/INDEX.md points at these documents, which do not exist on disk:\n  "
        + "\n  ".join(dangling)
        + "\n\nEither restore the file or remove the reference. A reference to "
        "a file that is gone sends the next agent looking for prose that was "
        "deleted, and reads as though the index is complete."
    )


def test_claude_md_points_at_the_index() -> None:
    assert INDEX_REF in _read(CLAUDE_MD), (
        "CLAUDE.md no longer points at docs/INDEX.md, so a clean-context agent "
        "cannot find the docs index. Restore the one-line pointer under "
        '"Docs index".'
    )
