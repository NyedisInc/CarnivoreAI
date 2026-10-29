
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "src" / "core" / "pack"

LEGACY_FLAT = {
    "store", "ddl", "views", "spawn", "admission", "settings", "push", "routing", "activity", "alerts", "alpha", "answers",
    "author_path", "auto_trust", "body_create", "body_death", "body", "closeout", "commit_guard", "commit", "company_agent",
    "company_desk", "conflicts", "create", "definition", "delivery", "desk", "effort", "export", "facade", "fact_index",
    "facts", "gitrun", "guard", "launch", "leaders", "learning", "memory", "names", "naming_rules", "node_order", "owner_message",
    "profiles", "project_agent", "project_removal", "promotion_store", "promotion", "question_events", "receipts", "rename",
    "reply_mirror",
}
ALLOWED_FLAT = {"__init__"}


def test_no_flat_swarm_module_reappears_under_pack():
    flat = {p.stem for p in PACK.glob("*.py")}
    assert not (flat & LEGACY_FLAT), f"flat Swarm modules back under src/core/pack/: {sorted(flat & LEGACY_FLAT)}"
    assert flat <= ALLOWED_FLAT, f"a flat module under src/core/pack/: {sorted(flat - ALLOWED_FLAT)}"


def test_old_route_and_tool_module_names_stay_free():
    assert not (ROOT / "src" / "api" / "pack_routes.py").exists()
    assert not (ROOT / "src" / "core" / "mcp" / "pack_tools.py").exists()

