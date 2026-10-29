
from __future__ import annotations

import json
import os
from pathlib import Path

from src.core.pack.skills import rules
from src.core.pack.skills.doc import Choices, build_document
from src.core.pack.skills.scan import scan_root, scan_skill

FAKE_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    root = tmp_path / ".claude" / "skills"
    _write(root, "clean/SKILL.md", "# clean\n")
    _write(root, "clean/refs/a.md", "a\n")
    _write(root, "linked/SKILL.md")
    os.symlink("/etc/hosts", root / "linked" / "hosts")
    _write(root, "envy/sub/.env", "A=1\n")
    _write(root, "envy/SKILL.md")
    _write(root, "setty/SKILL.md")
    _write(root, "setty/x/settings.json", json.dumps({"env": {"A": "b"}}))
    _write(root, "vendor/SKILL.md", f"token {FAKE_TOKEN}\n")
    _write(root, "big/SKILL.md")
    (root / "big" / "blob.bin").write_bytes(b"0" * (rules.MAX_FILE_BYTES + 1))
    _write(root, "synced/SKILL.md")
    _write(root, "withmods/SKILL.md", "# m\n")
    _write(root, "withmods/node_modules/pkg/index.js", f"{FAKE_TOKEN}\n")
    _write(root, "withmods/__pycache__/m.pyc", "junk")
    return root


def _build(root: Path, choices: Choices):
    scans = {"claude": scan_root(root, "claude")}
    return build_document(alpha="A", gen=1, made_at=1_000, choices=choices, scans=scans)


def test_document_holds_back_exactly_the_bad_skills(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = _build(root, Choices(mode="all"))
    assert result.problem is None and result.document is not None
    doc = result.document
    synced = {(f, n) for f, n, _ in doc["skills"]}
    held = {(f, n): why for f, n, why in doc["held"]}
    assert synced == {("claude", "clean"), ("claude", "withmods")}
    assert set(held) == {("claude", k) for k in ("linked", "envy", "setty", "vendor", "big")}
    assert held[("claude", "linked")] == "link inside"
    assert held[("claude", "envy")] == "holds a credential file: sub/.env"
    assert held[("claude", "setty")] == "holds settings with env or headers: x/settings.json"
    assert held[("claude", "vendor")].startswith("credential pattern in SKILL.md line 1")
    assert held[("claude", "big")] == "too large"
    assert FAKE_TOKEN not in json.dumps(doc)
    assert all(n != "synced" for _, n, _ in doc["skills"]) and ("claude", "synced") not in held


def test_node_modules_never_moves_the_digest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = scan_root(root, "claude").skills["withmods"].digest
    _write(root, "withmods/node_modules/other/x.js", "changed\n")
    _write(root, "withmods/__pycache__/n.pyc", "more")
    after = scan_root(root, "claude").skills["withmods"]
    assert after.digest == before and after.problem is None
    assert all("node_modules" not in f.path for f in after.files)
    _write(root, "withmods/SKILL.md", "# changed\n")
    assert scan_root(root, "claude").skills["withmods"].digest != before


def test_choices_select_and_missing_on_alpha_is_held(tmp_path: Path) -> None:
    root = _root(tmp_path)
    some = Choices(mode="some", include=frozenset({("claude", "clean"), ("claude", "gone")}))
    doc = _build(root, some).document
    assert [(f, n) for f, n, _ in doc["skills"]] == [("claude", "clean")]
    assert ["claude", "gone", "missing on alpha"] in doc["held"]
    off = _build(root, Choices(mode="off")).document
    assert off["skills"] == [] and off["held"] == []
    excl = _build(root, Choices(mode="all", exclude=frozenset({("claude", "clean")}))).document
    assert ("claude", "clean") not in {(f, n) for f, n, _ in excl["skills"]}


def test_unreadable_root_is_not_healthy_and_builds_no_document(tmp_path: Path) -> None:
    root = _root(tmp_path)
    link = tmp_path / "linkroot"
    os.symlink(root, link)
    linked = scan_root(link, "claude")
    assert not linked.healthy and linked.skills == {}
    root.chmod(0)
    try:
        if os.access(root, os.R_OK):
            return
        scan = scan_root(root, "claude")
        assert not scan.healthy
        result = build_document(
            alpha="A", gen=1, made_at=1, choices=Choices(mode="all"), scans={"claude": scan}
        )
        assert result.document is None and result.problem == f"cannot read {root}"
    finally:
        root.chmod(0o755)
    absent = scan_root(tmp_path / "nope", "codex")
    assert absent.healthy and absent.skills == {}


def test_rules_refuse_unsafe_names_and_paths_and_clashes() -> None:
    for bad in ("../x", "/abs", "a\\b", "a\0b", ".system", "synced", "node_modules", "huddle", "a/b", ".hid"):
        assert rules.skill_name_problem(bad), bad
    assert rules.skill_name_problem("sme") is None
    for bad in ("../x", "/abs", "a\\b", "a\0b", "node_modules/x", "a//b", "./a", "a" * 256, "/".join("d" * 13 for _ in range(13))):
        assert rules.path_problem(bad), bad
    assert rules.path_problem("refs/a.md") is None
    assert rules.collision(["A.md", "a.md"]) is not None
    assert rules.collision(["café", "café"]) is not None
    assert rules.collision(["a.md", "b.md"]) is None


def test_a_hard_linked_file_holds_the_skill_back(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("not in the skill\n")
    os.link(outside, root / "clean" / "linked-in.md")
    os.makedirs(root / "clean" / "node_modules" / "p")
    os.link(outside, root / "clean" / "node_modules" / "p" / "pnpm-store.js")
    assert scan_skill(root / "clean", "clean").problem == "hard link inside"
    os.unlink(root / "clean" / "linked-in.md")
    assert scan_skill(root / "clean", "clean").problem is None
