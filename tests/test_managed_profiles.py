
from __future__ import annotations

import ast
import os
import stat
import sys
import tempfile
import unicodedata
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import (
    MANAGED_ROOT,
    ProviderAccount,
    managed_dir_for,
    profile_dir_for,
)
from src.core.provider_ledger import managed_profiles


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)




def test_the_managed_root_is_named_once_and_is_the_carnivore_one() -> None:
    assert MANAGED_ROOT == "~/.carnivore/accounts"


def test_a_managed_dir_is_the_account_id_under_the_root(home) -> None:
    assert managed_dir_for("claude1") == str(home / ".carnivore/accounts/claude1")


def test_a_managed_dir_is_absolute(home) -> None:
    assert os.path.isabs(managed_dir_for("claude1"))


def test_a_managed_dir_is_nfc_normalised(home, monkeypatch) -> None:
    decomposed = str(home) + "/café"
    monkeypatch.setenv("HOME", decomposed)
    path = managed_dir_for("claude1")
    assert path == unicodedata.normalize("NFC", path)


def test_an_id_that_is_not_the_validated_slug_is_refused(home) -> None:
    for bad in ["../escape", "a/b", ".", "..", "UPPER", "", "with space"]:
        with pytest.raises(ValueError):
            managed_dir_for(bad)


def test_a_traversal_can_never_reach_outside_the_root(home) -> None:
    with pytest.raises(ValueError):
        managed_dir_for("../../etc")




def test_a_managed_claude_account_uses_its_managed_directory(home) -> None:
    account = ProviderAccount(
        id="claude1",
        name="Claude 1",
        provider="claude",
        claude_config_dir="~/.claude",
        managed=True,
    )
    assert profile_dir_for(account) == managed_dir_for("claude1")


def test_a_managed_codex_account_uses_the_same_directory_shape(home) -> None:
    account = ProviderAccount(
        id="codex1", name="Codex 1", provider="codex", managed=True
    )
    assert profile_dir_for(account) == managed_dir_for("codex1")


def test_an_unmanaged_claude_account_uses_its_pointer_as_written(home) -> None:
    account = ProviderAccount(
        id="work", name="Work", provider="claude", claude_config_dir="~/.claude-work"
    )
    assert profile_dir_for(account) == "~/.claude-work"


def test_an_unmanaged_codex_account_uses_its_codex_home(home) -> None:
    account = ProviderAccount(
        id="plus", name="Plus", provider="codex", codex_home="~/.codex-plus"
    )
    assert profile_dir_for(account) == "~/.codex-plus"


def test_a_managed_rows_explicit_pointer_is_ignored(home) -> None:
    account = ProviderAccount(
        id="claude1",
        name="Claude 1",
        provider="claude",
        claude_config_dir="/somewhere/else",
        managed=True,
    )
    assert profile_dir_for(account) == managed_dir_for("claude1")




def test_creating_a_profile_makes_the_directory(home) -> None:
    path = managed_profiles.ensure_managed_dir("claude1")
    assert Path(path).is_dir()
    assert path == managed_dir_for("claude1")


def test_the_directory_is_0700(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))
    assert mode_of(path) == 0o700


def test_the_parents_are_0700_too(home) -> None:
    managed_profiles.ensure_managed_dir("claude1")
    assert mode_of(home / ".carnivore") == 0o700
    assert mode_of(home / ".carnivore/accounts") == 0o700


def test_a_permissive_umask_does_not_widen_it(home) -> None:
    previous = os.umask(0o000)
    try:
        path = Path(managed_profiles.ensure_managed_dir("claude1"))
    finally:
        os.umask(previous)
    assert mode_of(path) == 0o700
    assert mode_of(home / ".carnivore/accounts") == 0o700


def test_creating_it_twice_is_the_same_answer_and_still_0700(home) -> None:
    first = managed_profiles.ensure_managed_dir("claude1")
    second = managed_profiles.ensure_managed_dir("claude1")
    assert first == second
    assert mode_of(Path(second)) == 0o700


def test_a_directory_widened_by_hand_is_narrowed_again(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))
    path.chmod(0o755)
    managed_profiles.ensure_managed_dir("claude1")
    assert mode_of(path) == 0o700


def test_an_existing_login_inside_it_is_left_alone(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))
    (path / ".credentials.json").write_text("{}")
    managed_profiles.ensure_managed_dir("claude1")
    assert (path / ".credentials.json").read_text() == "{}"


def test_creation_refuses_an_id_that_is_not_the_validated_slug(home) -> None:
    with pytest.raises(ValueError):
        managed_profiles.ensure_managed_dir("../escape")


def test_a_directory_that_cannot_be_made_is_a_named_refusal(home) -> None:
    (home / ".carnivore").write_text("not a directory")
    with pytest.raises(managed_profiles.ManagedProfileError):
        managed_profiles.ensure_managed_dir("claude1")




def test_a_managed_directory_is_recognised_as_one(home) -> None:
    managed_profiles.ensure_managed_dir("claude1")
    assert managed_profiles.is_managed_path(managed_dir_for("claude1")) is True


def test_a_hand_written_pointer_is_not_a_managed_directory(home) -> None:
    (home / ".claude").mkdir()
    assert managed_profiles.is_managed_path(str(home / ".claude")) is False


def test_only_the_removal_function_can_delete_anything() -> None:
    tree = ast.parse(Path(managed_profiles.__file__).read_text())
    deleting = {"rmtree", "remove", "rmdir", "unlink"}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else ""
            )
            if name in deleting:
                assert function.name == "remove_managed_dir", (
                    f"{name} is called from {function.name}"
                )




def test_a_symlinked_root_is_refused(home, tmp_path_factory) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (home / ".carnivore").symlink_to(elsewhere)

    with pytest.raises(managed_profiles.ManagedProfileError):
        managed_profiles.ensure_managed_dir("claude1")


def test_a_symlinked_root_is_left_exactly_as_it_was(home, tmp_path_factory) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere2")
    elsewhere.chmod(0o755)
    (home / ".carnivore").symlink_to(elsewhere)

    with pytest.raises(managed_profiles.ManagedProfileError):
        managed_profiles.ensure_managed_dir("claude1")

    assert mode_of(elsewhere) == 0o755
    assert list(elsewhere.iterdir()) == []


def test_a_symlinked_accounts_directory_is_refused(home, tmp_path_factory) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere3")
    (home / ".carnivore").mkdir()
    (home / ".carnivore" / "accounts").symlink_to(elsewhere)

    with pytest.raises(managed_profiles.ManagedProfileError):
        managed_profiles.ensure_managed_dir("claude1")


def test_a_symlinked_profile_directory_is_refused(home, tmp_path_factory) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere4")
    (home / ".carnivore" / "accounts").mkdir(parents=True)
    (home / ".carnivore" / "accounts" / "claude1").symlink_to(elsewhere)

    with pytest.raises(managed_profiles.ManagedProfileError):
        managed_profiles.ensure_managed_dir("claude1")


def test_an_ordinary_tree_is_still_created(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))

    assert path.is_dir()
    assert not path.is_symlink()
    assert mode_of(path) == 0o700


def test_the_created_directory_really_is_under_the_root(home) -> None:
    path = managed_profiles.ensure_managed_dir("claude1")

    assert managed_profiles.is_managed_path(path)


def test_an_id_with_a_trailing_newline_makes_no_directory(home) -> None:
    with pytest.raises(ValueError):
        managed_profiles.ensure_managed_dir("claude1\n")

    assert not (home / ".carnivore").exists()


def test_managed_dir_for_refuses_a_trailing_newline(home) -> None:
    assert not os.path.exists(home / ".carnivore")
    with pytest.raises(ValueError):
        managed_dir_for("claude1\n")




@pytest.fixture
def no_real_delete(monkeypatch):
    attempted: list = []

    def record(path, **kwargs) -> None:
        attempted.append(str(path))

    monkeypatch.setattr(managed_profiles.shutil, "rmtree", record)
    return attempted


def test_removing_a_managed_profile_deletes_that_directory(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REMOVED
    assert not path.exists()


def test_the_removal_takes_the_login_inside_it(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))
    (path / ".credentials.json").write_text("{}")

    managed_profiles.remove_managed_dir("claude1")

    assert not (path / ".credentials.json").exists()


def test_it_removes_exactly_one_account_and_leaves_its_siblings(home) -> None:
    kept = Path(managed_profiles.ensure_managed_dir("claude2"))
    managed_profiles.ensure_managed_dir("claude1")

    managed_profiles.remove_managed_dir("claude1")

    assert kept.is_dir()
    assert (home / ".carnivore/accounts").is_dir()


def test_the_outcome_names_the_path_it_acted_on(home) -> None:
    managed_profiles.ensure_managed_dir("claude1")

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.path == managed_dir_for("claude1")


def test_an_absent_directory_is_a_no_op_success(home) -> None:
    (home / ".carnivore/accounts").mkdir(parents=True)

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_ABSENT


def test_a_root_that_was_never_made_is_also_absent(home) -> None:
    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_ABSENT


def test_a_symlinked_profile_directory_is_refused_for_a_removal(home, tmp_path_factory, no_real_delete) -> None:
    elsewhere = tmp_path_factory.mktemp("rm_leaf")
    (elsewhere / "theirs.txt").write_text("not ours")
    (home / ".carnivore/accounts").mkdir(parents=True)
    (home / ".carnivore/accounts/claude1").symlink_to(elsewhere)

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REFUSED
    assert no_real_delete == []
    assert (elsewhere / "theirs.txt").exists()


def test_a_symlinked_accounts_directory_is_refused_for_a_removal(home, tmp_path_factory, no_real_delete) -> None:
    elsewhere = tmp_path_factory.mktemp("rm_accounts")
    (elsewhere / "claude1").mkdir()
    (elsewhere / "claude1" / "theirs.txt").write_text("not ours")
    (home / ".carnivore").mkdir()
    (home / ".carnivore/accounts").symlink_to(elsewhere)

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REFUSED
    assert no_real_delete == []
    assert (elsewhere / "claude1" / "theirs.txt").exists()


def test_a_symlinked_root_is_refused_for_a_removal(home, tmp_path_factory, no_real_delete) -> None:
    elsewhere = tmp_path_factory.mktemp("rm_root")
    (elsewhere / "accounts" / "claude1").mkdir(parents=True)
    (elsewhere / "accounts" / "claude1" / "theirs.txt").write_text("not ours")
    (home / ".carnivore").symlink_to(elsewhere)

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REFUSED
    assert no_real_delete == []
    assert (elsewhere / "accounts" / "claude1" / "theirs.txt").exists()


def test_a_file_where_the_profile_should_be_is_refused(home, no_real_delete) -> None:
    (home / ".carnivore/accounts").mkdir(parents=True)
    (home / ".carnivore/accounts/claude1").write_text("not a directory")

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REFUSED
    assert no_real_delete == []
    assert (home / ".carnivore/accounts/claude1").exists()


def test_an_id_that_is_not_the_validated_slug_deletes_nothing(home, no_real_delete) -> None:
    for bad in ["../escape", "a/b", "..", "UPPER", "", "claude1\n"]:
        with pytest.raises(ValueError):
            managed_profiles.remove_managed_dir(bad)
    assert no_real_delete == []


def test_a_delete_that_the_disk_refuses_is_reported_and_never_raised(
    home, monkeypatch
) -> None:
    managed_profiles.ensure_managed_dir("claude1")

    def explode(path, onexc=None, **kwargs) -> None:
        onexc(os.rmdir, str(path), PermissionError("nope"))

    monkeypatch.setattr(managed_profiles.shutil, "rmtree", explode)

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REFUSED


def test_the_ordinary_removal_still_happens(home) -> None:
    path = Path(managed_profiles.ensure_managed_dir("claude1"))
    assert path.is_dir()

    outcome = managed_profiles.remove_managed_dir("claude1")

    assert outcome.status == managed_profiles.DIRECTORY_REMOVED
    assert not path.exists()
