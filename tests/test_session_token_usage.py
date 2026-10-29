
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tok_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tok_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_token_usage import claude_reader, codex_reader
from src.core.session_token_usage.model_table import window_for_model
from src.core.session_token_usage.reader import (
    SessionSubject,
    read_session_token_usage,
)

UUID = "11111111-2222-3333-4444-555555555555"


def _assistant(
    message_id: str,
    model: str,
    *,
    inp: int,
    cache_creation: int,
    cache_read: int,
    out: int,
) -> Dict[str, Any]:
    return {
        "type": "assistant",
        "cwd": "/tmp/project",
        "sessionId": UUID,
        "uuid": message_id + "-line",
        "message": {
            "id": message_id,
            "role": "assistant",
            "model": model,
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": inp,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": out,
                "service_tier": "standard",
            },
        },
    }


def _write_lines(path: Path, lines: List[str]) -> None:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _claude_corpus(tmp_path: Path, lines: List[str]) -> Path:
    corpus = tmp_path / "projects"
    project = corpus / "-tmp-project"
    project.mkdir(parents=True)
    _write_lines(project / f"{UUID}.jsonl", lines)
    return corpus




def test_claude_sums_assistant_usage_skipping_malformed_and_usageless(tmp_path):
    lines = [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps(
            _assistant("msg_1", "claude-opus-5", inp=10, cache_creation=100,
                       cache_read=1000, out=5)
        ),
        "{this is not json",
        json.dumps(
            {"type": "assistant", "message": {"id": "msg_x", "model": "claude-opus-5"}}
        ),
        json.dumps(
            _assistant("msg_2", "claude-sonnet-5", inp=20, cache_creation=200,
                       cache_read=2000, out=7)
        ),
        json.dumps(
            _assistant("msg_3", "claude-haiku-4-5", inp=30, cache_creation=300,
                       cache_read=3000, out=9)
        ),
    ]
    corpus = _claude_corpus(tmp_path, lines)

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "ok"
    assert usage.family == "claude"
    assert usage.input_tokens == 60
    assert usage.cache_creation_input_tokens == 600
    assert usage.cache_read_input_tokens == 6000
    assert usage.output_tokens == 21
    assert usage.total_tokens == 6681
    assert usage.model == "claude-haiku-4-5"
    assert usage.model_display_name == "Haiku 4.5"
    assert usage.model_cost_tier == 2


def test_a_model_the_table_does_not_carry_reads_ok_with_no_name_and_no_tier(tmp_path):
    corpus = _claude_corpus(tmp_path, [
        json.dumps(_assistant("msg_1", "acme-unpriced-9", inp=10, cache_creation=0,
                              cache_read=0, out=5)),
    ])

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "ok"
    assert usage.input_tokens == 10
    assert usage.model == "acme-unpriced-9"
    assert usage.model_display_name is None
    assert usage.model_cost_tier is None
    assert usage.cost_estimate_usd is None
    assert usage.context_window_tokens is None


def test_an_unresolved_pick_keeps_the_known_model_and_claims_no_tier(tmp_path):
    corpus = _claude_corpus(tmp_path, [
        json.dumps(_assistant("msg_1", "claude-opus-5", inp=10, cache_creation=0,
                              cache_read=0, out=5)),
        json.dumps({"type": "system", "subtype": "local_command",
                    "content": "Set model to `Fable 9000` for this session only"}),
    ])

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "ok"
    assert usage.model == "claude-opus-5"
    assert usage.model_display_name == "Fable 9000"
    assert usage.model_cost_tier is None
    assert usage.cost_estimate_usd is None
    assert usage.context_window_tokens is None
    assert usage.input_tokens == 10


def test_the_opus_5_5_pick_reads_with_its_own_name_and_tier(tmp_path):
    corpus = _claude_corpus(tmp_path, [
        json.dumps(_assistant("msg_1", "claude-opus-5", inp=10, cache_creation=0,
                              cache_read=0, out=5)),
        json.dumps({"type": "user", "message": {"role": "user", "content": (
            "<local-command-stdout>Set model to `Opus 5.5 (1M context)` and "
            "saved as your default for new sessions</local-command-stdout>")}}),
    ])

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.model == "claude-opus-5-5"
    assert usage.model_display_name == "Opus 5.5"
    assert usage.model_cost_tier == 4
    assert usage.context_window_tokens == 1_000_000


def test_claude_counts_one_message_id_once_however_many_lines_it_spans(tmp_path):
    record = _assistant(
        "msg_1", "claude-opus-5", inp=10, cache_creation=0, cache_read=0, out=5
    )
    lines = [json.dumps(record), json.dumps(record), json.dumps(record)]
    corpus = _claude_corpus(tmp_path, lines)

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.total_tokens == 15


def test_claude_context_used_is_the_last_turn_not_the_session_total(tmp_path):
    lines = [
        json.dumps(
            _assistant("msg_1", "claude-haiku-4-5", inp=10, cache_creation=100,
                       cache_read=1000, out=5)
        ),
        json.dumps(
            _assistant("msg_2", "claude-haiku-4-5", inp=30, cache_creation=300,
                       cache_read=3000, out=9)
        ),
    ]
    corpus = _claude_corpus(tmp_path, lines)

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.context_used_tokens == 3330
    assert usage.context_window_tokens == 200_000
    assert usage.context_remaining_pct == 98.3


def test_claude_missing_transcript_is_absent_not_unchecked(tmp_path):
    corpus = tmp_path / "projects"
    (corpus / "-tmp-other").mkdir(parents=True)

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "absent"
    assert usage.family == "claude"
    assert usage.total_tokens is None


def test_claude_no_conversation_id_is_absent(tmp_path):
    usage = read_session_token_usage(
        SessionSubject("claude", None, None), projects_dir=tmp_path
    )
    assert usage.state == "absent"
    assert usage.input_tokens is None


def test_claude_zero_byte_transcript_is_absent(tmp_path):
    corpus = _claude_corpus(tmp_path, [])

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "absent"
    assert usage.family == "claude"
    assert usage.total_tokens is None


def test_claude_user_only_transcript_is_absent(tmp_path):
    corpus = _claude_corpus(tmp_path, [json.dumps({
        "type": "user",
        "cwd": "/tmp/project",
        "sessionId": UUID,
        "uuid": "user-1",
        "message": {"role": "user", "content": "hello"},
    })])

    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None), projects_dir=corpus
    )

    assert usage.state == "absent"
    assert usage.family == "claude"
    assert usage.total_tokens is None


def test_claude_unreadable_corpus_is_unchecked_never_absent(tmp_path):
    usage = read_session_token_usage(
        SessionSubject("claude", UUID, None),
        projects_dir=tmp_path / "does-not-exist",
    )

    assert usage.state == "unchecked"
    assert usage.total_tokens is None
    assert usage.cost_estimate_usd is None


def test_claude_unreadable_file_is_unchecked(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("running as root, so a mode 000 file is still readable")
    corpus = _claude_corpus(tmp_path, [json.dumps(_assistant(
        "msg_1", "claude-opus-5", inp=1, cache_creation=0, cache_read=0, out=1
    ))])
    transcript = corpus / "-tmp-project" / f"{UUID}.jsonl"
    transcript.chmod(0o000)
    try:
        usage = read_session_token_usage(
            SessionSubject("claude", UUID, None), projects_dir=corpus
        )
    finally:
        transcript.chmod(0o644)

    assert usage.state == "unchecked"
    assert usage.input_tokens is None


def test_read_transcript_totals_returns_none_for_a_missing_file(tmp_path):
    assert claude_reader.read_transcript_totals(tmp_path / "nope.jsonl") is None




def _rollout(tmp_path: Path, *, with_meta: bool = True,
             counts: List[Dict[str, Any]] = None,
             models: List[str] = None) -> Path:
    lines: List[str] = []
    if with_meta:
        lines.append(json.dumps({
            "type": "session_meta",
            "payload": {"id": UUID, "cwd": "/tmp/project", "cli_version": "1.0"},
        }))
    for index, info in enumerate(counts or []):
        if models and index < len(models):
            lines.append(json.dumps({
                "type": "turn_context",
                "payload": {"turn_id": f"t{index}", "model": models[index],
                            "cwd": "/tmp/project"},
            }))
        lines.append(json.dumps({
            "type": "event_msg",
            "payload": {"type": "token_count", "info": info,
                        "rate_limits": {"limit_id": "premium"}},
        }))
    path = tmp_path / f"rollout-2026-09-19T00-00-00-{UUID}.jsonl"
    _write_lines(path, lines)
    return path


def _info(*, total_input: int, cached: int, cache_write: int, output: int,
          last_input: int, window: int) -> Dict[str, Any]:
    return {
        "total_token_usage": {
            "input_tokens": total_input,
            "cached_input_tokens": cached,
            "cache_write_input_tokens": cache_write,
            "output_tokens": output,
            "reasoning_output_tokens": 0,
            "total_tokens": total_input + output,
        },
        "last_token_usage": {
            "input_tokens": last_input,
            "cached_input_tokens": last_input // 2,
            "cache_write_input_tokens": 0,
            "output_tokens": 10,
            "reasoning_output_tokens": 0,
            "total_tokens": last_input + 10,
        },
        "model_context_window": window,
    }


def test_codex_takes_the_last_token_count_and_ignores_the_earlier_one(tmp_path,
                                                                     monkeypatch):
    path = _rollout(
        tmp_path,
        counts=[
            _info(total_input=10, cached=0, cache_write=0, output=1,
                  last_input=10, window=999),
            _info(total_input=1000, cached=800, cache_write=50, output=100,
                  last_input=50_000, window=200_000),
        ],
        models=["gpt-5", "gpt-5-codex"],
    )
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: str(path),
    )

    usage = read_session_token_usage(SessionSubject("codex", UUID, None))

    assert usage.state == "ok"
    assert usage.family == "codex"
    assert usage.model == "gpt-5-codex"
    assert usage.input_tokens == 150
    assert usage.cache_read_input_tokens == 800
    assert usage.cache_creation_input_tokens == 50
    assert usage.output_tokens == 100
    assert usage.total_tokens == 1100
    assert usage.context_used_tokens == 50_000
    assert usage.context_window_tokens == 200_000
    assert usage.context_remaining_pct == 75.0


def test_codex_window_comes_from_the_file_over_the_price_table(tmp_path,
                                                               monkeypatch):
    path = _rollout(
        tmp_path,
        counts=[_info(total_input=100, cached=0, cache_write=0, output=10,
                      last_input=100, window=123_456)],
        models=["gpt-5"],
    )
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: str(path),
    )

    usage = read_session_token_usage(SessionSubject("codex", UUID, None))

    assert window_for_model("gpt-5") == 400_000
    assert usage.context_window_tokens == 123_456


def test_codex_session_meta_with_no_turn_is_absent(tmp_path, monkeypatch):
    path = _rollout(tmp_path, counts=[], models=[])
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: str(path),
    )

    usage = read_session_token_usage(SessionSubject("codex", UUID, None))

    assert usage.state == "absent"
    assert usage.family == "codex"
    assert usage.total_tokens is None


def test_codex_file_with_neither_meta_nor_counts_is_absent(tmp_path, monkeypatch):
    path = _rollout(tmp_path, with_meta=False, counts=[], models=[])
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: str(path),
    )

    usage = read_session_token_usage(SessionSubject("codex", UUID, None))

    assert usage.state == "absent"
    assert usage.total_tokens is None


def test_codex_no_rollout_path_is_absent(monkeypatch):
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: None,
    )
    usage = read_session_token_usage(SessionSubject("codex", UUID, None))
    assert usage.state == "absent"


def test_codex_unopenable_rollout_is_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.core.session_token_usage.reader.rollout_path_for",
        lambda home, uuid: str(tmp_path / "gone.jsonl"),
    )
    usage = read_session_token_usage(SessionSubject("codex", UUID, None))
    assert usage.state == "unchecked"
    assert usage.total_tokens is None


def test_codex_reader_reads_only_a_bounded_tail(tmp_path):
    path = _rollout(
        tmp_path,
        counts=[_info(total_input=100, cached=0, cache_write=0, output=10,
                      last_input=100, window=1000)],
        models=["gpt-5"],
    )
    assert codex_reader.TAIL_BYTES >= 1024 * 1024
    usage = codex_reader.read_codex_usage(str(path))
    assert usage is not None and usage.output_tokens == 10




@pytest.mark.parametrize("family", ["hermes", "openclaw", "local", "shell"])
def test_a_family_with_no_reader_is_unchecked_never_a_claude_read(family, tmp_path):
    usage = read_session_token_usage(
        SessionSubject(family, UUID, None), projects_dir=tmp_path
    )

    assert usage.state == "unchecked"
    assert usage.family is None
    assert family in (usage.detail or "")
    assert usage.total_tokens is None


def test_no_family_at_all_is_unchecked(tmp_path):
    usage = read_session_token_usage(
        SessionSubject(None, UUID, None), projects_dir=tmp_path
    )
    assert usage.state == "unchecked"
