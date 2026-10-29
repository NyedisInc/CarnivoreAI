
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.test_catalog_bootstrap import load_script

SENTINEL_KEY = "sk-or-v1-NOTAREALKEY-canary-0123456789"

ROW: Dict[str, str] = {
    "submission_id": "a" * 32,
    "handle": "example-owner",
    "name": "work",
    "version": "1.0.0",
}


@pytest.fixture()
def gate() -> Any:
    return load_script("batch_review")


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    root = tmp_path / "CarnivoreAI-Skills"
    (root / "tools" / "index_builder").mkdir(parents=True)
    (root / "tools" / "index_builder" / "__main__.py").write_text("", encoding="utf-8")
    (root / "catalog.yml").write_text("repo: Example-owner/CarnivoreAI-Skills\n", encoding="utf-8")
    (root / "skills" / ROW["handle"] / ROW["name"]).mkdir(parents=True)
    return root


class _Recorder:

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, command: List[str], **kwargs: Any) -> Any:
        self.calls.append({"command": list(command), **kwargs})
        return subprocess.CompletedProcess(
            command, self.returncode, stdout="reviewed\n", stderr=""
        )


class TestTheKeyNeverReachesTheProcessTable:

    def test_the_key_goes_in_the_environment_and_NOT_in_argv(
        self, gate: Any, catalog: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        recorder = _Recorder(returncode=0)
        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        monkeypatch.setattr(gate.subprocess, "run", recorder)

        assert gate.security_review(catalog, ROW, override=None) == 0

        call = recorder.calls[0]
        assert call["env"]["OPENROUTER_SECRET_VALUE"] == SENTINEL_KEY
        for argument in call["command"]:
            assert SENTINEL_KEY not in argument, "the key reached the command line"

    def test_the_key_is_never_printed(
        self, gate: Any, catalog: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        monkeypatch.setattr(gate.subprocess, "run", _Recorder(returncode=0))

        gate.security_review(catalog, ROW, override=None)

        captured = capsys.readouterr()
        assert SENTINEL_KEY not in captured.out
        assert SENTINEL_KEY not in captured.err

    def test_read_review_key_prints_the_secret_id_and_never_its_value(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0] if a else [], 0, stdout=SENTINEL_KEY + "\n", stderr=""
            ),
        )
        assert gate.read_review_key() == SENTINEL_KEY
        captured = capsys.readouterr()
        assert SENTINEL_KEY not in captured.out
        assert SENTINEL_KEY not in captured.err

    def test_the_reviewer_is_run_WITHOUT_A_SHELL(
        self, gate: Any, catalog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(returncode=0)
        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        monkeypatch.setattr(gate.subprocess, "run", recorder)

        gate.security_review(catalog, ROW, override='a reason with "quotes" and $HOME')

        call = recorder.calls[0]
        assert call.get("shell", False) is False
        assert isinstance(call["command"], list)


class TestAReviewThatCouldNotRunIsNotAPass:

    def test_a_missing_index_builder_refuses_rather_than_returning_zero(
        self, gate: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        bare = tmp_path / "empty"
        bare.mkdir()
        monkeypatch.setattr(gate, "builder_tools", lambda catalog: bare)
        with pytest.raises(gate.FetchError):
            gate.security_review(bare, ROW, override=None)

    def test_a_timeout_refuses_rather_than_returning_zero(
        self, gate: Any, catalog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def timeout(*args: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="review", timeout=1)

        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        monkeypatch.setattr(gate.subprocess, "run", timeout)
        with pytest.raises(gate.FetchError):
            gate.security_review(catalog, ROW, override=None)

    def test_an_unreadable_key_refuses_rather_than_reviewing_nothing(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0] if a else [], 1, stdout="", stderr="AccessDenied"
            ),
        )
        with pytest.raises(gate.FetchError):
            gate.read_review_key()

    def test_the_reviewers_exit_code_is_passed_through_unchanged(
        self, gate: Any, catalog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gate, "read_review_key", lambda: SENTINEL_KEY)
        monkeypatch.setattr(gate.subprocess, "run", _Recorder(returncode=1))
        assert gate.security_review(catalog, ROW, override=None) == 1
