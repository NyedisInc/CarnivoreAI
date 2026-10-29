
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "core"
SCANNED = [ROOT / "db_steps.py", ROOT / "db_schema_audit.py", ROOT / "db_models.py"] + sorted(
    (ROOT / "db_ddl").glob("*.py")
)


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def test_schema_modules_import_nothing_from_save_pipeline() -> None:
    assert len(SCANNED) >= 6 and all(p.is_file() for p in SCANNED)
    seen = 0
    for path in SCANNED:
        mods = _imported_modules(path)
        seen += len(mods)
        bad = sorted(m for m in mods if "save_pipeline" in m)
        assert not bad, f"{path.name} imports {bad}"
    assert seen > 20


def test_the_moved_ddl_still_exports_what_the_steps_run() -> None:
    from src.core.db_ddl import pipeline, search_index

    for name in ("apply_v51", "apply_v53", "DDL_V51", "V53_COLUMNS", "REVERSAL_SQL_V51", "REVERSAL_SQL_V53"):
        assert hasattr(pipeline, name), name
    for name in ("apply_v52", "apply_v55", "DDL_V52", "DDL_V55", "V55_COLUMNS", "REVERSAL_SQL_V52", "REVERSAL_SQL_V55"):
        assert hasattr(search_index, name), name
    assert not (ROOT / "save_pipeline" / "ddl.py").exists()
    assert not (ROOT / "save_pipeline" / "search_index" / "ddl.py").exists()
