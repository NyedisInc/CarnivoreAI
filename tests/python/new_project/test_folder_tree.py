
from __future__ import annotations

import os

from src.core.new_project.org_tree import build_tree


def _tree(tmp_path):
    org = tmp_path / "Org"
    for rel in ("Acme/Globex/payroll", "Acme/Globex/camera", "Personal/games", ".hidden/x", "node_modules/y"):
        (org / rel).mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "secret").mkdir(parents=True)
    (org / "Acme" / "link").symlink_to(outside)
    return org


def _names(nodes):
    return [n["name"] for n in nodes]


def test_lists_folders_a_z_skips_hidden_and_never_follows_a_symlink(tmp_path):
    org = _tree(tmp_path)
    tree = build_tree(str(org), [], [])
    assert _names(tree["nodes"]) == ["Acme", "Personal"]
    imc = tree["nodes"][0]
    assert _names(imc["children"]) == ["Globex"]
    assert tree["truncated"] is False


def test_tags_projects_and_companies(tmp_path):
    org = _tree(tmp_path)
    tree = build_tree(str(org), [str(org / "Acme/Globex/payroll")], [{"id": 13, "name": "Globex", "folder": str(org / "Acme/Globex")}])
    calda = tree["nodes"][0]["children"][0]
    assert calda["company"] == {"id": 13, "name": "Globex"} and calda["project"] is False
    payroll = next(n for n in calda["children"] if n["name"] == "payroll")
    assert payroll["project"] is True and payroll["company"] is None


def test_depth_and_node_budget_bound_the_walk(tmp_path):
    org = _tree(tmp_path)
    shallow = build_tree(str(org), [], [], depth=1)
    assert shallow["nodes"][0]["children"] == []
    capped = build_tree(str(org), [], [], max_nodes=2)
    assert capped["truncated"] is True
