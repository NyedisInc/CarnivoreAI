
from pathlib import Path

import pytest

from scripts.help import check_pages
from tests.python.help_pages.helpers import git, make_repo, write_page

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path / "r")
    write_page(r, "help/a/index.md", sha=git(r, "rev-parse", "--short", "HEAD"))
    return r


def run(repo, capsys, *extra):
    code = check_pages.main(["--repo", str(repo), *extra])
    return code, capsys.readouterr().out


def test_clean_exits_0_and_reports_coverage(repo, capsys):
    code, out = run(repo, capsys)
    assert code == 0
    assert "coverage: 1 catalog features have no help page" in out


def test_strict_coverage_lists_and_fails(repo, capsys):
    code, out = run(repo, capsys, "--strict-coverage")
    assert code == 1 and "feature 'other' has no help page" in out


def test_unknown_feature_id_is_a_finding(repo, capsys):
    write_page(repo, "help/a/index.md", features="feat, ghost", sha="HEAD")
    code, out = run(repo, capsys)
    assert code == 1 and "feature id 'ghost'" in out


def test_missing_source_is_a_finding(repo, capsys):
    write_page(repo, "help/a/index.md", sources=("src/a.py", "src/gone.py"), sha="HEAD")
    code, out = run(repo, capsys)
    assert code == 1 and "source 'src/gone.py' does not exist" in out


def test_source_changed_after_verified_at_is_a_finding(repo, capsys):
    sha = git(repo, "rev-parse", "--short", "HEAD")
    (repo / "src" / "a.py").write_text("x = 2\n")
    git(repo, "commit", "-qam", "change")
    write_page(repo, "help/a/index.md", sha=sha)
    code, out = run(repo, capsys)
    assert code == 1 and "changed since verified_at" in out
    write_page(repo, "help/a/index.md", sha=git(repo, "rev-parse", "--short", "HEAD"))
    assert run(repo, capsys)[0] == 0


def test_unrelated_commit_does_not_flag(repo, capsys):
    (repo / "other.txt").write_text("y")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-qm", "unrelated")
    assert run(repo, capsys)[0] == 0


def test_unknown_sha_is_a_finding(repo, capsys):
    write_page(repo, "help/a/index.md", sha="deadbee")
    code, out = run(repo, capsys)
    assert code == 1 and "<verified_at not a commit>" in out


def test_could_not_check_exits_2(tmp_path, capsys):
    assert run(tmp_path, capsys)[0] == 2
    r = make_repo(tmp_path / "r")
    (r / "help").mkdir()
    assert run(r, capsys)[0] == 2
    write_page(r, "help/a/index.md", sha="HEAD")
    for f in (r / "features" / "catalog").glob("*.json"):
        f.unlink()
    assert run(r, capsys)[0] == 2


def test_not_a_git_repo_exits_2(tmp_path, capsys):
    r = tmp_path / "plain"
    (r / "features" / "catalog").mkdir(parents=True)
    (r / "features" / "catalog" / "feat.json").write_text("{}")
    (r / "src").mkdir()
    (r / "src" / "a.py").write_text("")
    write_page(r, "help/a/index.md", sha="abc1234")
    assert run(r, capsys)[0] == 2


def test_malformed_page_exits_2(repo, capsys):
    (repo / "help" / "a" / "broken.md").write_text("no front matter")
    assert run(repo, capsys)[0] == 2
