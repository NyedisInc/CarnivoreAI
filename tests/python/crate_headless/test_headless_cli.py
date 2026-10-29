
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from scripts.crate import cli
from scripts.crate.client import CrateClient
from tests.python.cplugs.crate.api_world import stop_runner
from tests.python.crate_headless.world import TwoInstalls

HOSTS = ("--from-url", "http://a.invalid", "--to-url", "http://b.invalid")


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def run(w: TwoInstalls, *argv: str) -> Tuple[int, str, str]:
    clients = {"from": w.client_a, "to": w.client_b, "": w.client_b}

    def factory(prefix: str, args: argparse.Namespace) -> CrateClient:
        return clients[prefix]

    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), factory=factory, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cycle_with_undo_exits_zero_and_prints_the_whole_run_as_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    code, out, err = run(w, "cycle", *HOSTS, "project", w.a.world.root1, "--relocate", str(w.install.projects / "Proj One"), "--undo", "--json")
    assert code == 0 and err == ""
    answer: Dict[str, Any] = json.loads(out)
    assert answer["ok"] is True and answer["verify"]["ok"] and answer["restore"]["provenance"] == "foreign"
    assert answer["send"]["sha256"] == answer["export"]["sha256"] and answer["undo"]["result"]["state"] == "undone"
    assert w.b_counts() == {"sessions": 0, "projects": 0}


def test_each_subcommand_in_text_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    code, out, _ = run_a(w, "export", "project", w.a.world.root1)
    exported = json.loads(out)
    assert code == 0 and exported["ok"] and len(exported["sha256"]) == 64
    code, out, _ = run(w, "send", *HOSTS, exported["bundle_id"])
    assert code == 0 and out.startswith("sent crate-")
    name = out.split()[1]
    root = str(w.install.projects / "Proj One")
    code, out, _ = run(w, "restore", "--url", "http://b.invalid", name, "--relocate", root)
    assert code == 0 and out.startswith("restored imp-") and "(foreign)" in out
    import_id = out.split()[1]
    code, out, _ = run(w, "verify", "--url", "http://b.invalid", import_id, "--sha256", exported["sha256"])
    assert code == 0 and out.startswith(f"verified {import_id}")
    code, out, _ = run(w, "verify", "--url", "http://b.invalid", import_id, "--sha256", "0" * 64, "--json")
    assert code == 7 and json.loads(out)["error"]["class"] == "VerifyError"
    code, out, _ = run(w, "undo", "--url", "http://b.invalid", import_id)
    assert code == 0 and out.startswith(f"undone {import_id}")
    assert w.b_counts() == {"sessions": 0, "projects": 0}


def run_a(w: TwoInstalls, *argv: str) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main([argv[0], "--url", "http://a.invalid", *argv[1:], "--json"], factory=lambda p, a: w.client_a, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_a_blocked_restore_exits_five_with_the_list_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    code, out, err = run(w, "cycle", *HOSTS, "project", w.a.world.root1)
    assert code == 5 and out == ""
    assert "relocate_required" in err and "--relocate ROOT" in err and "nothing was written" in err
    assert w.b_counts() == {"sessions": 0, "projects": 0} and w.client_b.imports() == {"imports": []}

    code, out, err = run(w, "cycle", *HOSTS, "project", w.a.world.root1, "--json")
    failure = json.loads(out)
    assert code == 5 and failure["ok"] is False and failure["error"]["exit_code"] == 5
    assert [b["code"] for b in failure["error"]["detail"]] == ["relocate_required"]


def test_no_token_is_exit_three_and_an_unreachable_host_is_exit_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARNIVORE_TOKEN", raising=False)
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["setup", "--url", "http://127.0.0.1:1", "--json"], out=out, err=err) == 3
    assert json.loads(out.getvalue())["error"]["class"] == "AuthError"

    monkeypatch.setenv("CARNIVORE_TOKEN", "t")
    out = io.StringIO()
    assert cli.main(["setup", "--url", "http://127.0.0.1:1", "--json"], out=out, err=err) == 10
    assert json.loads(out.getvalue())["error"]["class"] == "NetworkError"


def test_a_bad_command_line_is_exit_two() -> None:
    with pytest.raises(SystemExit) as bad:
        cli.main(["restore"], out=io.StringIO(), err=io.StringIO())
    assert bad.value.code == 2


def test_the_help_lists_every_exit_code() -> None:
    text = cli._epilog()
    for code in ("0", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
        assert f"\n  {code}  " in "\n" + text


def test_restore_accepts_the_bare_bundle_id_that_export_prints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    code, out, _ = run_a(w, "export", "project", w.a.world.root1)
    exported = json.loads(out)
    code, out, _ = run(w, "send", *HOSTS, exported["bundle_id"])
    bare = out.split()[1].removesuffix(".crate")
    code, out, err = run(w, "restore", "--url", "http://b.invalid", bare, "--relocate", str(w.install.projects / "Proj One"))
    assert code == 0 and out.startswith("restored imp-"), err
