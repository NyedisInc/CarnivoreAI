
from __future__ import annotations

import os

from src.core.new_project.landing_check import check_landing

ORG = "/h/Org"
CALDA = {"id": 13, "name": "Globex", "folder": "/h/Org/Acme/Globex"}
Acme = {"id": 1, "name": "Acme", "folder": "/h/Org/Acme"}
COMPANIES = [Acme, CALDA, {"id": 9, "name": "Scratch", "folder": None}]
PROJECTS = [{"name": "payroll", "root": "/h/Org/Acme/Globex/payroll"}]


def _check(path, company_id=13, **kw):
    kw.setdefault("temp_roots", [])
    kw.setdefault("home", "/h")
    return check_landing(path, org_root=ORG, projects=PROJECTS, companies=COMPANIES, company_id=company_id, **kw)


def _codes(verdict, level):
    return [f.code for f in verdict.findings if f.level == level]


def test_a_clean_folder_under_its_company_is_ok():
    v = _check("/h/Org/Acme/Globex/invoice-sync")
    assert v.ok and _codes(v, "block") == [] and _codes(v, "warn") == []
    assert [f.code for f in v.findings] == ["company", "clean"]


def test_blocks_scratch_and_temp_folders():
    assert _codes(_check("/h/Org/Scratch/x"), "block") == ["scratch"]
    assert _codes(_check("/h/Org/Acme/tmp/x"), "block") == ["scratch"]
    assert _codes(_check("/var/folders/ab/T/x", temp_roots=["/var/folders"]), "block") == ["scratch"]
    assert not _check("/h/Org/Scratch/x").ok
    assert _check("/h/Org/Acme/tmpl/x").ok


def test_blocks_the_account_sign_in_folders():
    v = _check("/h/.carnivore/accounts/work/proj")
    assert not v.ok and "sign_in_folder" in _codes(v, "block")


def test_blocks_a_folder_that_already_is_a_project_and_warns_inside_one():
    assert _codes(_check("/h/Org/Acme/Globex/payroll"), "block") == ["already_project"]
    inside = _check("/h/Org/Acme/Globex/payroll/sub")
    assert inside.ok and "inside_project" in _codes(inside, "warn")


def test_warns_outside_org_a_different_company_and_no_company():
    assert "outside_org" in _codes(_check("/h/elsewhere/x", company_id=None), "warn")
    other = _check("/h/Org/Acme/Globex/x", company_id=1)
    assert other.ok and _codes(other, "warn") == ["other_company"]
    assert next(f for f in other.findings if f.code == "other_company").params == {"owner": "Globex", "company": "Acme"}
    none = _check("/h/Org/Acme/Globex/x", company_id=None)
    assert none.ok and "no_company" in _codes(none, "warn")


def test_an_empty_path_blocks():
    assert not _check("").ok and _codes(_check("  "), "block") == ["pick_folder"]


def test_the_deepest_company_folder_owns_a_path():
    v = _check("/h/Org/Acme/Globex/x", company_id=13)
    assert _codes(v, "warn") == []
