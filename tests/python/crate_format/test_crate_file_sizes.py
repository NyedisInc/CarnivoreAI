
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDERS = ("src/core/crate_format", "src/core/crate_crypto", "src/core/blobcodec", "src/cplugs/crate")
FILES = ("src/cplugs/sdk/blob_codec.py", "src/cplugs/sdk/crate_format.py", "src/cplugs/sdk/crate_sources.py",
         "src/cplugs/sdk/crate_rows.py", "src/cplugs/sdk/exports.py")
LIMIT = 500


def _sources():
    for folder in FOLDERS:
        yield from (ROOT / folder).rglob("*.py")
    for name in FILES:
        if (ROOT / name).exists():
            yield ROOT / name


def test_every_crate_file_is_under_500_lines() -> None:
    sizes = {str(p.relative_to(ROOT)): len(p.read_text().splitlines()) for p in _sources()}
    assert len(sizes) >= 20
    assert {name: n for name, n in sizes.items() if n >= LIMIT} == {}
