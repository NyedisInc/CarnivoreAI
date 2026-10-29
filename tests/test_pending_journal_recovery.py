
from __future__ import annotations

import ast
import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pj_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pj_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills.sweeper import SkillSweeper
from src.core.skills.journal_containment import REFUSAL_CODES, journal_refusal
from src.core.skills.journal_recovery import (
    OUTCOME_ALREADY_COMPLETE,
    OUTCOME_FINISHED,
    OUTCOME_NOTHING,
    OUTCOME_REFUSED,
    OUTCOME_REVERSED,
    REFUSED_DIR_NAME,
    list_pending,
    recover_pending,
)
from src.core.skills.update_journal import (
    STEP_SWAPPING,
    STEP_WRITTEN,
    PendingJournal,
    apply_swap,
    displaced_path,
    pending_path,
    read_pending,
    write_pending,
)
from tests.test_installer_refuses_real_home import guard_violations
from tests.test_skill_installer import FakeInstallRoots

STAMP = "20260915T120000Z"
INSTALL_ID = "i1a2b3"

GUARDED_MODULES = (
    ROOT / "src" / "core" / "skills" / "update_journal.py",
    ROOT / "src" / "core" / "skills" / "journal_recovery.py",
    ROOT / "src" / "core" / "skills" / "installer.py",
    ROOT / "src" / "core" / "skills" / "install_plan.py",
)


@pytest.fixture
def roots(tmp_path) -> FakeInstallRoots:
    made = FakeInstallRoots(tmp_path / "roots")
    made.make_roots()
    return made


def folder(path: Path, marker: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {marker}\n", encoding="utf-8")
    return path


def journal_for(roots: FakeInstallRoots, step: int) -> PendingJournal:
    return PendingJournal(
        install_id=INSTALL_ID,
        kind="skill",
        name="review",
        scope="global",
        project_path=None,
        target=str(roots.claude_skills() / "review"),
        staged=str(roots.claude_skills() / "review.new"),
        trash=str(roots.trash_dir("claude", "global", None)),
        stamp=STAMP,
        step=step,
    )




def test_a_journal_round_trips_through_disk(roots):
    written = journal_for(roots, STEP_WRITTEN)

    path = write_pending(roots.pending_dir(), INSTALL_ID, written)
    read_back = read_pending(path)

    assert read_back == written
    assert path == pending_path(roots.pending_dir(), INSTALL_ID)
    assert list_pending(roots.pending_dir()) == (path,)


def test_a_malformed_journal_answers_none_and_is_left_alone(roots):
    roots.pending_dir().mkdir(parents=True)
    broken = roots.pending_dir() / "bad.json"
    broken.write_text("{not json", encoding="utf-8")

    assert read_pending(broken) is None
    counts = recover_pending(roots.pending_dir(), roots)
    assert counts["unreadable"] == 1
    assert broken.exists(), "an unreadable journal is not deleted"


def test_an_install_id_with_a_separator_is_refused(roots):
    with pytest.raises(ValueError):
        pending_path(roots.pending_dir(), "../escape")


def test_recovery_refuses_a_directory_that_is_not_the_journal_directory(roots):
    with pytest.raises(ValueError):
        recover_pending(roots.staging_dir(), roots)




def test_a_crash_after_the_first_rename_is_finished(roots):
    journal = journal_for(roots, STEP_SWAPPING)
    staged = folder(Path(journal.staged), "new")
    folder(displaced_path(journal), "theirs")
    path = write_pending(roots.pending_dir(), INSTALL_ID, journal)
    assert not Path(journal.target).exists()

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_FINISHED] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# new\n"
    assert not staged.exists(), "the staged copy is consumed, not left as debris"
    assert not path.exists(), "the journal is deleted"


def test_a_crash_before_any_rename_is_reversed(roots):
    journal = journal_for(roots, STEP_WRITTEN)
    staged = folder(Path(journal.staged), "new")
    folder(Path(journal.target), "theirs")
    path = write_pending(roots.pending_dir(), INSTALL_ID, journal)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_REVERSED] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# theirs\n"
    assert not staged.exists()
    assert not path.exists()


def test_the_filesystem_beats_the_step_field(roots):
    journal = journal_for(roots, STEP_WRITTEN)
    folder(Path(journal.staged), "new")
    folder(displaced_path(journal), "theirs")
    write_pending(roots.pending_dir(), INSTALL_ID, journal)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_FINISHED] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# new\n"


def test_a_target_lost_with_a_copy_in_the_trash_is_put_back(roots):
    journal = journal_for(roots, STEP_SWAPPING)
    displaced = folder(displaced_path(journal), "theirs")
    path = write_pending(roots.pending_dir(), INSTALL_ID, journal)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_REVERSED] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# theirs\n"
    assert not displaced.exists()
    assert not path.exists()


def test_a_crash_after_the_journal_was_the_only_thing_left(roots):
    journal = journal_for(roots, STEP_SWAPPING)
    folder(Path(journal.target), "new")
    path = write_pending(roots.pending_dir(), INSTALL_ID, journal)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_ALREADY_COMPLETE] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# new\n"
    assert not path.exists()


def test_a_journal_naming_nothing_on_disk_is_dropped(roots):
    journal = journal_for(roots, STEP_WRITTEN)
    path = write_pending(roots.pending_dir(), INSTALL_ID, journal)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_NOTHING] == 1
    assert not path.exists()




def test_apply_swap_replaces_the_target_and_clears_the_journal(roots):
    journal = journal_for(roots, STEP_WRITTEN)
    folder(Path(journal.staged), "new")
    folder(Path(journal.target), "theirs")
    write_pending(roots.pending_dir(), INSTALL_ID, journal)

    displaced = apply_swap(journal, roots=roots)

    assert (Path(journal.target) / "SKILL.md").read_text() == "# new\n"
    assert (displaced / "SKILL.md").read_text() == "# theirs\n"
    assert displaced == displaced_path(journal)
    assert list_pending(roots.pending_dir()) == ()


def test_apply_swap_marks_the_journal_before_it_moves_anything(roots, monkeypatch):
    journal = journal_for(roots, STEP_WRITTEN)
    folder(Path(journal.staged), "new")
    folder(Path(journal.target), "theirs")
    write_pending(roots.pending_dir(), INSTALL_ID, journal)
    seen: list[int] = []

    def exploding_swap(*_args, **_kwargs):
        found = read_pending(pending_path(roots.pending_dir(), INSTALL_ID))
        seen.append(found.step if found else -1)
        raise OSError("power cut")

    monkeypatch.setattr("src.core.skills.update_journal.swap_in", exploding_swap)

    with pytest.raises(OSError):
        apply_swap(journal, roots=roots)

    assert seen == [STEP_SWAPPING]
    assert list_pending(roots.pending_dir()) != (), "the journal survives the crash"




@pytest.mark.asyncio
async def test_the_boot_pass_runs_the_recovery(roots):
    journal = journal_for(roots, STEP_SWAPPING)
    folder(Path(journal.staged), "new")
    folder(displaced_path(journal), "theirs")
    write_pending(roots.pending_dir(), INSTALL_ID, journal)

    report = await SkillSweeper(install_roots=roots).run_boot_pass()

    assert report["recovered"][OUTCOME_FINISHED] == 1
    assert (Path(journal.target) / "SKILL.md").read_text() == "# new\n"
    assert list_pending(roots.pending_dir()) == ()
    assert "staging_removed" in report, "the age sweep still runs"


@pytest.mark.asyncio
async def test_the_recovery_runs_before_the_age_sweep(roots, monkeypatch):
    order: list[str] = []
    real_recover = SkillSweeper._recover_once
    real_sweep = SkillSweeper._sweep_once

    def watched_recover(self):
        order.append("recover")
        return real_recover(self)

    def watched_sweep(self):
        order.append("sweep")
        return real_sweep(self)

    monkeypatch.setattr(SkillSweeper, "_recover_once", watched_recover)
    monkeypatch.setattr(SkillSweeper, "_sweep_once", watched_sweep)

    await SkillSweeper(install_roots=roots).run_boot_pass()

    assert order == ["recover", "sweep"]




def forged(roots, **overrides) -> PendingJournal:
    return dataclasses.replace(journal_for(roots, STEP_SWAPPING), **overrides)


def victim(tmp_path: Path) -> Path:
    directory = tmp_path / "victim"
    directory.mkdir()
    (directory / "irreplaceable.txt").write_text("years of work\n")
    return directory


def run_one(roots, journal: PendingJournal) -> dict[str, int]:
    write_pending(roots.pending_dir(), INSTALL_ID, journal)
    return recover_pending(roots.pending_dir(), roots)


def assert_refused(roots, counts: dict[str, int]) -> Path:
    assert counts[OUTCOME_REFUSED] == 1, counts
    assert list_pending(roots.pending_dir()) == (), "it is out of the recovery set"
    moved = roots.pending_dir() / REFUSED_DIR_NAME / f"{INSTALL_ID}.json"
    assert moved.is_file(), "a refused journal is evidence and is kept"
    return moved


def test_a_forged_target_is_refused_and_the_directory_it_named_survives(
    roots, tmp_path
):
    doomed = victim(tmp_path)

    counts = run_one(roots, forged(roots, target=str(doomed)))

    assert_refused(roots, counts)
    assert (doomed / "irreplaceable.txt").read_text() == "years of work\n"


def test_a_journal_naming_a_root_itself_is_refused(roots):
    folder(roots.claude_skills() / "keep-me", "mine")

    counts = run_one(roots, forged(roots, target=str(roots.claude_skills())))

    assert_refused(roots, counts)
    assert (roots.claude_skills() / "keep-me" / "SKILL.md").is_file()
    assert roots.claude_skills().is_dir()


def test_a_forged_staged_copy_is_refused_and_nothing_is_copied(roots, tmp_path):
    theirs = folder(tmp_path / "attacker" / "review", "attacker content")
    folder(Path(journal_for(roots, STEP_SWAPPING).target), "mine")

    counts = run_one(roots, forged(roots, staged=str(theirs)))

    assert_refused(roots, counts)
    target = Path(journal_for(roots, STEP_SWAPPING).target)
    assert (target / "SKILL.md").read_text() == "# mine\n"
    assert (theirs / "SKILL.md").is_file(), "nothing was consumed either"


def test_a_forged_trash_is_refused_and_what_it_named_survives(roots, tmp_path):
    elsewhere = victim(tmp_path)

    counts = run_one(roots, forged(roots, trash=str(elsewhere)))

    assert_refused(roots, counts)
    assert (elsewhere / "irreplaceable.txt").is_file()


def test_a_stamp_that_escapes_the_trash_is_refused(roots):
    counts = run_one(roots, forged(roots, stamp="../../../escape"))

    assert_refused(roots, counts)


def test_an_unsafe_name_is_refused_before_any_path_is_composed(roots):
    counts = run_one(roots, forged(roots, name=".system"))

    assert_refused(roots, counts)


def test_a_journal_whose_scope_does_not_match_its_target_is_refused(roots):
    counts = run_one(
        roots, forged(roots, scope="project", project_path="/tmp/not-this-project")
    )

    assert_refused(roots, counts)


def test_a_journal_missing_the_checkable_fields_is_left_alone(roots):
    roots.pending_dir().mkdir(parents=True)
    old_shape = roots.pending_dir() / "old.json"
    old_shape.write_text(
        json.dumps(
            {
                "install_id": "old",
                "target": "/etc",
                "staged": "/tmp/x",
                "trash": "/tmp/t",
                "stamp": STAMP,
                "step": 0,
            }
        ),
        encoding="utf-8",
    )

    assert read_pending(old_shape) is None
    counts = recover_pending(roots.pending_dir(), roots)

    assert counts["unreadable"] == 1
    assert counts[OUTCOME_REFUSED] == 0
    assert old_shape.exists()


def test_a_refusal_does_not_stop_the_valid_journal_beside_it(roots, tmp_path):
    good = journal_for(roots, STEP_SWAPPING)
    folder(Path(good.staged), "new")
    folder(displaced_path(good), "theirs")
    write_pending(roots.pending_dir(), INSTALL_ID, good)
    bad = dataclasses.replace(
        good, install_id="i2forged", target=str(victim(tmp_path))
    )
    write_pending(roots.pending_dir(), "i2forged", bad)

    counts = recover_pending(roots.pending_dir(), roots)

    assert counts[OUTCOME_FINISHED] == 1
    assert counts[OUTCOME_REFUSED] == 1
    assert (Path(good.target) / "SKILL.md").read_text() == "# new\n"
    assert (tmp_path / "victim" / "irreplaceable.txt").is_file()


def test_the_containment_check_can_be_satisfied_by_a_real_journal(roots):
    assert journal_refusal(journal_for(roots, STEP_WRITTEN), roots=roots) is None


def test_every_refusal_code_is_one_the_module_declares(roots, tmp_path):
    seen = set()
    for override in (
        {"name": ".system"},
        {"scope": "nonsense"},
        {"target": str(tmp_path / "elsewhere")},
        {"target": str(roots.claude_skills())},
        {"staged": str(tmp_path / "elsewhere" / "x")},
        {"trash": str(tmp_path / "elsewhere")},
        {"stamp": "../../escape"},
    ):
        refusal = journal_refusal(forged(roots, **override), roots=roots)
        assert refusal is not None, override
        seen.add(refusal.code)

    assert seen == set(REFUSAL_CODES), sorted(seen)



GUARDED_METHODS = frozenset(
    {"mkdir", "write_text", "write_bytes", "unlink", "touch", "rmdir"}
)


def method_write_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        guarded: list[tuple[int, str]] = []
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "assert_test_write_allowed"
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                guarded.append((node.lineno, node.args[0].id))

        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr not in GUARDED_METHODS:
                continue
            if not isinstance(target.value, ast.Name):
                violations.append(
                    f"{function.name}:{node.lineno}: .{target.attr}() on an "
                    "expression, so no guard can be matched against it; bind "
                    "it to a local first"
                )
                continue
            name = target.value.id
            if not any(
                line < node.lineno and guarded_name == name
                for line, guarded_name in guarded
            ):
                violations.append(
                    f"{function.name}:{node.lineno}: '{name}.{target.attr}()' "
                    f"with no earlier assert_test_write_allowed({name})"
                )
    return violations


@pytest.mark.parametrize("module", GUARDED_MODULES, ids=lambda p: p.name)
def test_no_unguarded_os_or_shutil_call_in_the_install_modules(module):
    violations = guard_violations(module.read_text())

    assert violations == [], f"{module.name}:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize("module", GUARDED_MODULES, ids=lambda p: p.name)
def test_no_unguarded_method_write_in_the_install_modules(module):
    violations = method_write_violations(module.read_text())

    assert violations == [], f"{module.name}:\n  " + "\n  ".join(violations)


def test_the_method_checker_found_something_to_check():
    found = [
        node.func.attr
        for module in GUARDED_MODULES
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in GUARDED_METHODS
    ]

    assert "mkdir" in found
    assert "write_text" in found
    assert len(found) >= 3, found


def test_the_method_checker_can_actually_fail():
    violations = method_write_violations(
        "def make(p):\n    p.mkdir()\n"
    )

    assert violations
    assert "mkdir" in violations[0]


def test_a_method_guard_on_the_wrong_variable_does_not_count():
    violations = method_write_violations(
        "def make(a, b):\n"
        "    assert_test_write_allowed(a)\n"
        "    b.write_text('x')\n"
    )

    assert len(violations) == 1
    assert "'b.write_text()'" in violations[0]
