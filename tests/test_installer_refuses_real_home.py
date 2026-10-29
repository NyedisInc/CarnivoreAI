
from __future__ import annotations

import ast
import contextlib
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nrh_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nrh_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.live_install_roots import LiveInstallRoots
from src.core.live_ports import LiveSettings
from src.core.skills import targets
from src.core.skills.targets import (
    copy_tree,
    move_to_trash,
    remove_tree,
    swap_in,
)
from src.core.test_write_guard import (
    OutsideTempWriteError,
    running_under_test,
    temp_roots,
)

TARGETS_SOURCE = ROOT / "src" / "core" / "skills" / "targets.py"


def _production_roots() -> LiveInstallRoots:
    return LiveInstallRoots(settings_reader=LiveSettings())




class RecorderTripped(RuntimeError):
    pass


REFUSED_SHUTIL: frozenset[str] = frozenset(
    {
        "copy",
        "copy2",
        "copyfile",
        "copymode",
        "copystat",
        "copytree",
        "make_archive",
        "move",
        "rmtree",
        "unpack_archive",
    }
)

REFUSED_OS: frozenset[str] = frozenset(
    {
        "chmod",
        "chown",
        "link",
        "makedirs",
        "mkdir",
        "open",
        "remove",
        "removedirs",
        "rename",
        "renames",
        "replace",
        "rmdir",
        "symlink",
        "truncate",
        "unlink",
        "utime",
    }
)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _assert_production_target(path: Path) -> None:
    resolved = path.resolve()

    for root in temp_roots():
        assert not _within(resolved, root), (
            f"{resolved} is under the temp root {root}, so refusing it "
            "would prove nothing about a real home"
        )

    homes = [Path.home().resolve()]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and codex_home.strip():
        homes.append(Path(codex_home).expanduser().resolve())

    assert any(_within(resolved, home) for home in homes), (
        f"{resolved} is under none of {[str(h) for h in homes]}, so this "
        "test is no longer pointed at the production roots it claims to be"
    )


class _CallRecorder:

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def refuse(self, name: str, args: tuple[Any, ...]) -> None:
        paths = tuple(
            str(arg) for arg in args if isinstance(arg, (str, os.PathLike))
        )
        self.calls.append((name, paths))
        raise RecorderTripped(
            f"{name} was reached with {paths}. The write guard in "
            "src/core/skills/targets.py did not stop it, so this recorder "
            "did. NOTHING WAS EXECUTED, and nothing on disk was touched."
        )


class _RefusingModule:

    def __init__(
        self,
        real: Any,
        refused: frozenset[str],
        recorder: _CallRecorder,
        label: str,
    ) -> None:
        self._real = real
        self._refused = refused
        self._recorder = recorder
        self._label = label

    def __getattr__(self, name: str) -> Any:
        if name in self._refused:
            recorder = self._recorder
            dotted = f"{self._label}.{name}"

            def _refuse(*args: Any, **kwargs: Any) -> None:
                recorder.refuse(dotted, args)

            return _refuse
        return getattr(self._real, name)


@contextlib.contextmanager
def _no_destructive_calls() -> Iterator[_CallRecorder]:
    recorder = _CallRecorder()

    def _refuse_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        recorder.refuse("Path.mkdir", (self,))

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch.object(
                targets,
                "shutil",
                _RefusingModule(shutil, REFUSED_SHUTIL, recorder, "shutil"),
            )
        )
        stack.enter_context(
            patch.object(
                targets,
                "os",
                _RefusingModule(os, REFUSED_OS, recorder, "os"),
            )
        )
        stack.enter_context(patch.object(Path, "mkdir", _refuse_mkdir))
        yield recorder




def test_the_suite_is_actually_running_under_the_guard():
    assert running_under_test() is True


def test_copying_into_the_real_claude_root_is_refused(tmp_path):
    roots = _production_roots()
    claude = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "claude"
    )
    source = tmp_path / "staged"
    source.mkdir()
    (source / "SKILL.md").write_text("x\n")
    destination = claude.leaf_dir / "cloude-negative-control"
    _assert_production_target(destination)

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            copy_tree(source, destination)

    assert recorder.calls == []
    assert not destination.exists()


def test_copying_into_the_real_codex_root_is_refused(tmp_path):
    roots = _production_roots()
    codex = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "codex"
    )
    source = tmp_path / "staged"
    source.mkdir()
    (source / "SKILL.md").write_text("x\n")
    destination = codex.leaf_dir / "cloude-negative-control"
    _assert_production_target(destination)

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            copy_tree(source, destination)

    assert recorder.calls == []
    assert not destination.exists()


def test_copying_into_the_real_user_themes_root_is_refused(tmp_path):
    from src.core.theme_paths import USER_THEMES_DIR_ENV_VAR

    with patch.dict(os.environ):
        os.environ.pop(USER_THEMES_DIR_ENV_VAR, None)

        roots = _production_roots()
        themes = next(
            t
            for t in roots.targets_for("theme", "global", None)
            if t.harness == "app"
        )
        source = tmp_path / "staged"
        source.mkdir()
        (source / "theme.json").write_text('{"id": "cloude-negative-control"}\n')
        destination = themes.leaf_dir / "cloude-negative-control"
        _assert_production_target(destination)

        with _no_destructive_calls() as recorder:
            with pytest.raises(OutsideTempWriteError):
                copy_tree(source, destination)

        assert recorder.calls == []
        assert not destination.exists()

def test_copying_a_plugin_into_the_real_claude_root_is_refused(tmp_path):
    roots = _production_roots()
    targets = roots.targets_for("plugin", "global", None)
    assert [t.harness for t in targets] == ["claude"]
    claude = targets[0]
    assert claude.leaf_dir.name == "skills"
    assert "plugins" not in claude.leaf_dir.parts

    source = tmp_path / "staged"
    (source / ".claude-plugin").mkdir(parents=True)
    (source / ".claude-plugin" / "plugin.json").write_text('{"name":"x"}\n')
    destination = claude.leaf_dir / "cloude-negative-control-plugin"
    _assert_production_target(destination)

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            copy_tree(source, destination)

    assert recorder.calls == []
    assert not destination.exists()


def test_moving_a_real_folder_to_the_real_trash_is_refused(tmp_path):
    roots = _production_roots()
    trash = roots.trash_dir("claude", "global", None)
    claude = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "claude"
    )
    trash_existed = trash.exists()
    _assert_production_target(trash)
    _assert_production_target(claude.leaf_dir / "anything")

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            move_to_trash(
                claude.leaf_dir / "anything", trash, "20260915T000000"
            )

    assert recorder.calls == []
    assert trash.exists() == trash_existed


def test_swapping_into_a_real_root_is_refused(tmp_path):
    roots = _production_roots()
    claude = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "claude"
    )
    live = claude.leaf_dir.parent
    if not live.exists():
        pytest.skip("no real ~/.claude on this machine to aim at")
    staged = tmp_path / "new"
    staged.mkdir()
    _assert_production_target(live)
    _assert_production_target(roots.trash_dir("claude", "global", None))

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            swap_in(
                staged,
                live,
                    trash_root=roots.trash_dir("claude", "global", None),
                stamp="20260915T000000",
            )

    assert recorder.calls == []
    assert live.exists()


def test_removing_a_real_harness_directory_is_refused():
    roots = _production_roots()
    claude = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "claude"
    )
    existed = claude.leaf_dir.exists()
    _assert_production_target(claude.leaf_dir)

    with _no_destructive_calls() as recorder:
        with pytest.raises(OutsideTempWriteError):
            remove_tree(claude.leaf_dir)

    assert recorder.calls == []
    assert claude.leaf_dir.exists() == existed


def test_the_same_operations_succeed_under_a_temp_root(tmp_path):
    source = tmp_path / "staged"
    source.mkdir()
    (source / "SKILL.md").write_text("real content\n")
    destination = tmp_path / "skills" / "sme"
    destination.parent.mkdir()

    copy_tree(source, destination)
    assert (destination / "SKILL.md").read_text() == "real content\n"

    displaced = move_to_trash(
        destination, tmp_path / ".carnivore-trash", "20260915T000000"
    )
    assert (displaced / "SKILL.md").is_file()
    assert not destination.exists()

    remove_tree(displaced)
    assert not displaced.exists()




def test_the_recorder_stops_the_delete_that_caused_the_incident():
    real_root = Path.home() / ".claude" / "skills"
    _assert_production_target(real_root)
    existed = real_root.exists()

    with _no_destructive_calls() as recorder:
        with pytest.raises(RecorderTripped) as excinfo:
            targets.shutil.rmtree(real_root)

    assert str(real_root) in str(excinfo.value)
    assert recorder.calls == [("shutil.rmtree", (str(real_root),))]
    assert real_root.exists() == existed


def test_the_recorder_stops_a_rename_and_a_directory_creation_too():
    real_root = Path.home() / ".claude" / "skills"
    trash = Path.home() / ".claude" / ".carnivore-trash"
    _assert_production_target(trash)
    trash_existed = trash.exists()

    with _no_destructive_calls() as recorder:
        with pytest.raises(RecorderTripped):
            targets.os.replace(real_root, trash)
        with pytest.raises(RecorderTripped):
            trash.mkdir(parents=True, exist_ok=True)

    assert [name for name, _paths in recorder.calls] == [
        "os.replace",
        "Path.mkdir",
    ]
    assert trash.exists() == trash_existed


def test_the_recorder_covers_every_primitive_the_guard_checker_knows_about():
    uncovered = []
    for dotted in GUARDED_CALLS:
        module, _dot, attribute = dotted.partition(".")
        refused = {"os": REFUSED_OS, "shutil": REFUSED_SHUTIL}.get(module)
        if refused is None or attribute not in refused:
            uncovered.append(dotted)

    assert uncovered == [], (
        "these destructive calls are guarded in targets.py but are NOT "
        f"refused by the recorder, so they have one stop, not two: {uncovered}"
    )
    assert GUARDED_CALLS, "the catalogue is empty, so this checked nothing"


def test_the_recorder_still_lets_the_reads_through():
    with _no_destructive_calls() as recorder:
        assert targets.os.path.lexists(str(Path.home())) is True
        assert callable(targets.shutil.disk_usage)

    assert recorder.calls == []



GUARDED_CALLS: dict[str, tuple[int, ...]] = {
    "os.replace": (0, 1),
    "os.unlink": (0,),
    "os.rename": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.copyfile": (1,),
    "shutil.copy": (1,),
    "shutil.copy2": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return None


def guard_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        guarded: list[tuple[int, str]] = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            if _dotted(node.func) != "assert_test_write_allowed":
                continue
            if node.args:
                named = _dotted(node.args[0])
                if named is not None:
                    guarded.append((node.lineno, named))

        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            positions = GUARDED_CALLS.get(name or "")
            if positions is None:
                continue
            for position in positions:
                if position >= len(node.args):
                    continue
                argument = _dotted(node.args[position])
                if argument is None:
                    violations.append(
                        f"{function.name}:{node.lineno}: {name} argument "
                        f"{position} is an expression, so no guard can be "
                        "matched against it; bind it to a local first"
                    )
                    continue
                covered = any(
                    guard_line < node.lineno and guard_name == argument
                    for guard_line, guard_name in guarded
                )
                if not covered:
                    violations.append(
                        f"{function.name}:{node.lineno}: {name} acts on "
                        f"'{argument}' with no earlier "
                        f"assert_test_write_allowed({argument})"
                    )
    return violations


def test_every_destructive_call_in_targets_is_guarded():
    violations = guard_violations(TARGETS_SOURCE.read_text())

    assert violations == [], (
        "src/core/skills/targets.py has a destructive call with no write "
        "guard in front of it:\n  " + "\n  ".join(violations)
    )


def test_the_checker_found_something_to_check():
    tree = ast.parse(TARGETS_SOURCE.read_text())
    found = [
        _dotted(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _dotted(node.func) in GUARDED_CALLS
    ]

    assert "os.replace" in found
    assert "shutil.rmtree" in found
    assert "os.unlink" in found
    assert "shutil.copyfile" in found
    assert len(found) >= 5, found


def test_the_source_checker_can_actually_fail():
    unguarded = (
        "import os\n"
        "def swap(a, b):\n"
        "    os.replace(a, b)\n"
    )

    violations = guard_violations(unguarded)

    assert violations, "the checker passed source with no guard at all"
    assert "os.replace" in violations[0]


def test_a_guard_on_the_wrong_variable_does_not_count():
    wrong_variable = (
        "import os\n"
        "def swap(a, b):\n"
        "    assert_test_write_allowed(a)\n"
        "    os.replace(a, b)\n"
    )

    violations = guard_violations(wrong_variable)

    assert len(violations) == 1
    assert "'b'" in violations[0]


def test_a_guard_after_the_call_does_not_count():
    too_late = (
        "import os\n"
        "def wipe(p):\n"
        "    os.unlink(p)\n"
        "    assert_test_write_allowed(p)\n"
    )

    violations = guard_violations(too_late)

    assert len(violations) == 1
    assert "os.unlink" in violations[0]




def _real_root_fingerprint() -> str:
    roots = _production_roots()
    digest = hashlib.sha256()
    for harness in ("claude", "codex"):
        digest.update(harness.encode("utf-8"))
        for name in roots.root_listing(harness):
            digest.update(b"\x00")
            digest.update(name.encode("utf-8"))
        digest.update(b"\n")
    for target in roots.legacy_targets_for("skill", "global", None):
        digest.update(b"legacy\n")
        try:
            names = sorted(entry.name for entry in os.scandir(target.leaf_dir))
        except OSError:
            names = []
        for name in names:
            digest.update(b"\x00")
            digest.update(name.encode("utf-8"))
    return digest.hexdigest()


@pytest.fixture(scope="module", autouse=True)
def real_roots_unchanged():
    before = _real_root_fingerprint()
    yield
    after = _real_root_fingerprint()
    assert after == before, (
        "the listing of a REAL harness skills root changed while this "
        "module ran. Something wrote into the owner's ~/.claude/skills or "
        "~/.codex/skills. The write guard fires only where it is called, "
        "so look for an unguarded write path before anything else."
    )


def test_the_canary_reads_the_real_roots_and_not_a_temp_one():
    roots = _production_roots()
    claude = next(
        t for t in roots.targets_for("skill", "global", None) if t.harness == "claude"
    )

    assert claude.leaf_dir == Path.home() / ".claude" / "skills"
    assert isinstance(_real_root_fingerprint(), str)


def test_the_fingerprint_changes_when_a_listing_changes(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    (codex_home / "skills").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".agents" / "skills").mkdir(parents=True)

    before = _real_root_fingerprint()
    (codex_home / "skills" / "new-thing").mkdir()
    middle = _real_root_fingerprint()
    (tmp_path / "home" / ".agents" / "skills" / "newer-thing").mkdir()
    after = _real_root_fingerprint()

    assert before != middle != after


def test_the_listing_never_creates_the_root_it_reads(tmp_path, monkeypatch):
    codex_home = tmp_path / "absent-codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("HOME", str(tmp_path / "absent-home"))
    roots = _production_roots()

    assert roots.root_listing("codex") == ()
    assert not codex_home.exists()
    assert not (tmp_path / "absent-home").exists()
