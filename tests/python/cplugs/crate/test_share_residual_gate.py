
from __future__ import annotations

import json
import secrets
import string
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.cplugs.crate import share as S
from src.cplugs.crate import share_out as SO
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import ExportRefused, run_export
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request
from tests.python.inventory.world import CONV_A


def _token() -> str:
    return "ghp_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))


def _uescaped_line(token: str) -> bytes:
    return b'{"content":"' + "".join(f"\\u{ord(c):04x}" for c in token).encode() + b'"}\n'


def _world_with(tmp_path: Path, line: bytes) -> SimpleNamespace:
    w = make_world(tmp_path)
    (Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A}.jsonl").write_bytes(line)
    return w


def _share_folder_empty(w: SimpleNamespace) -> bool:
    folder = Path(w.state) / "crates" / "share"
    return not folder.is_dir() or not any(folder.iterdir())


def test_the_second_pass_clears_a_uescaped_token() -> None:
    token = _token()
    stats = S.ShareStats()
    out = b"".join(S.transform_lines(iter([_uescaped_line(token)]), stats, last_may_be_torn=True, member="m"))
    assert token not in json.loads(out)["content"] and stats.findings.get("github_token") == 1


def test_without_the_second_pass_the_gate_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S, "second_pass", lambda value: value)
    with pytest.raises(S.ShareResidualSecret) as caught:
        list(S.transform_lines(iter([_uescaped_line(_token())]), S.ShareStats(), last_may_be_torn=True, member="m"))
    assert caught.value.detectors == ["github_token"] and "ghp_" not in str(caught.value)
    w = _world_with(tmp_path, _uescaped_line(_token()))
    env = env_for(w)
    with pytest.raises(S.ShareResidualSecret):
        run_export(env, build_plan(env, session_request(variant="share")), JobHandle("g"))
    assert _share_folder_empty(w)


def test_without_redaction_the_gate_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _token()
    w = _world_with(tmp_path, json.dumps({"content": f"key {token}"}).encode() + b"\n")
    env = env_for(w)
    plan = build_plan(env, session_request(variant="share"))
    monkeypatch.setattr(cs, "redact", lambda text: text)
    with pytest.raises(S.ShareResidualSecret) as caught:
        run_export(env, plan, JobHandle("r"))
    assert token not in str(caught.value) and _share_folder_empty(w)
    with pytest.raises(S.ShareResidualSecret):
        S.transform_text(f"plain {token}\n".encode(), S.ShareStats(), member="t")


def test_a_json_member_is_gated() -> None:
    S.gate_member("reconcile.json", [{"reason": "a reason"}])
    with pytest.raises(S.ShareResidualSecret):
        S.gate_member("reconcile.json", [{"reason": f"a {_token()}"}])
    assert "*" * 20 in str(S.clean_text(f"title {_token()}", "crate.json"))


def test_a_codex_conversation_is_unsupported_and_filed_flat() -> None:
    plan = SimpleNamespace(conversations=[{"id": "c1", "family": "codex", "title": None, "session_uuid": None,
                                           "working_dir": "/w", "main_rel": "sessions/2026/10/10/rollout-x-c1.jsonl",
                                           "enc_folder": None, "origin": "disk", "orphan": False}])
    (record,) = SO.conversation_records(plan, {})
    assert record.resume == "unsupported_codex" and record.main_rel == "sessions/_shared/rollout-x-c1.jsonl"
    assert record.working_dir is None


def test_an_air_gapped_project_refuses_at_export_time(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    plan = build_plan(env, project_request(w, "share"))
    assert plan.ok
    with closing(connect(db_path_for(w.state))) as conn:
        conn.execute("UPDATE projects SET air_gap = 1 WHERE id = ?", (w.p1,))
        conn.commit()
    with pytest.raises(ExportRefused):
        run_export(env, plan, JobHandle("a"))
    assert _share_folder_empty(w)
