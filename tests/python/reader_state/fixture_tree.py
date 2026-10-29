
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_N_FILES = 8
UNCHANGED = ("s5", "s6", "s7")
REWRITTEN = ("s3", "s4")
GROWN = ("s0", "s1", "s2")
UNDELIVERABLE = ("a1b2c3d4e5f6a7b8c", "uds:/tmp/cc-socks/1.sock", "ghost")
LATE = "late"


def project_dir(root: Path) -> Path:
    return root / "projects" / "-fixture-slug"


def transcript_path(root: Path, name: str) -> Path:
    return project_dir(root) / f"{name}.jsonl"


def all_names() -> List[str]:
    return [f"s{i}" for i in range(_N_FILES)]


def _turn(msg_id: str, tokens: int, model: str, effort: str = "") -> Dict[str, Any]:
    record: Dict[str, Any] = {"type": "assistant", "message": {
        "role": "assistant", "id": msg_id, "model": model,
        "usage": {"input_tokens": tokens, "output_tokens": 5,
                  "cache_read_input_tokens": 3, "cache_creation_input_tokens": 1}}}
    if effort:
        record["effort"] = effort
    return record


def _command(text: str) -> Dict[str, Any]:
    return {"type": "system", "subtype": "local_command", "content": text}


def _ultra(entered: bool) -> Dict[str, Any]:
    kind = "ultra_effort_enter" if entered else "ultra_effort_exit"
    return {"type": "attachment", "attachment": {"type": kind}}


def _stamp(n: int) -> str:
    return f"2026-10-05T10:{n // 60:02d}:{n % 60:02d}.000Z"


def _assistant_calls(n: int, *blocks: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "assistant", "timestamp": _stamp(n),
            "message": {"role": "assistant", "content": list(blocks)}}


def _tool_use(name: str, tool_id: str, **inputs: Any) -> Dict[str, Any]:
    return {"type": "tool_use", "name": name, "id": tool_id, "input": inputs}


def _tool_result(n: int, tool_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "user", "timestamp": _stamp(n), "toolUseResult": result,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]}}


def _peer(n: int, msg_id: str, body: str) -> Dict[str, Any]:
    return {"type": "user", "timestamp": _stamp(n), "message": {"role": "user", "content": body},
            "origin": {"kind": "peer", "msg_id": msg_id, "name": "bob", "body": body}}


def _timer_and_mail_lines(name: str) -> List[Dict[str, Any]]:
    return [
        {"type": "user", "timestamp": _stamp(1), "message": {"role": "user", "content": "go"}},
        _assistant_calls(2, _tool_use("ScheduleWakeup", f"{name}_w1", delaySeconds=60, prompt="a")),
        _tool_result(3, f"{name}_w1", {"scheduledFor": 1}),
        _assistant_calls(4, _tool_use("ScheduleWakeup", f"{name}_w2", delaySeconds=120, prompt="b"),
                         _tool_use("CronCreate", f"{name}_c1", cron="*/5 * * * *", prompt="c"),
                         _tool_use("Bash", f"{name}_b1", command="sleep 30 && echo done",
                                   run_in_background=True)),
        _assistant_calls(5, _tool_use("SendMessage", f"{name}_m1", to="bob", message=f"{name} one"),
                         _tool_use("SendMessage", f"{name}_m2", to="bob", message=f"{name} two")),
        _tool_result(6, f"{name}_m1", {"success": True, "msg_id": f"{name}-native-1"}),
        _peer(7, f"{name}-peer-1", f"{name} hello"),
        _assistant_calls(8, *[_tool_use("SendMessage", f"{name}_u{i}", to=to, message=f"{name} nobody {i}")
                              for i, to in enumerate((*UNDELIVERABLE, LATE))]),
        *[_tool_result(9 + i, f"{name}_u{i}", {"success": True, "msg_id": f"{name}-native-u{i}"})
          for i in range(len(UNDELIVERABLE) + 1)],
    ]


def _dump(records: List[Dict[str, Any]]) -> str:
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)


def _phase1_text(name: str) -> str:
    first = _turn(f"{name}_m0", 10, "claude-opus-5", "high")
    records = [first,
               _turn(f"{name}_m1", 20, "claude-opus-5"),
               _turn(f"{name}_m1", 20, "claude-opus-5"),
               _command("Set model to `Sonnet 5` for this session only"),
               _turn(f"{name}_m2", 30, "claude-sonnet-5", "medium"),
               _command("Set effort level to ultracode (this session only)"),
               _ultra(True), _turn(f"{name}_m3", 40, "claude-sonnet-5", "xhigh")]
    if name in ("s0", "s1"):
        records.append(_ultra(False))
    text = _dump(records + _timer_and_mail_lines(name))
    if name == "s0":
        text += json.dumps(_turn("s0_half", 7, "claude-opus-5"))[:-9]
    return text


def build_phase1(root: Path) -> None:
    project_dir(root).mkdir(parents=True, exist_ok=True)
    for name in all_names():
        transcript_path(root, name).write_text(_phase1_text(name))
    from tests.python.reader_state import fixture_subagents

    fixture_subagents.build_phase1(root)


def apply_phase2(root: Path) -> None:
    for name in GROWN:
        path = transcript_path(root, name)
        with open(path, "ab") as handle:
            if name == "s0":
                handle.write(json.dumps(_turn("s0_half", 7, "claude-opus-5"))[-9:].encode() + b"\n")
            handle.write(_dump([_turn(f"{name}_m4", 50, "claude-opus-5"),
                                _command("Set effort level to low (this session only)"),
                                _tool_result(20, f"{name}_w2", {"scheduledFor": 2}),
                                _tool_result(21, f"{name}_m2", {"success": True, "msg_id": f"{name}-native-2"}),
                                _peer(22, f"{name}-peer-2", f"{name} later")]).encode())
    transcript_path(root, "s3").write_text(_dump([
        _turn("s3_new", 11, "claude-haiku-4-5"),
        _assistant_calls(2, _tool_use("SendMessage", "s3_n1", to="bob", message="s3 new")),
        _tool_result(3, "s3_n1", {"success": True, "msg_id": "s3-native-new"})]))
    old = _phase1_text("s4").encode()
    new = old.replace(b'"input_tokens":10,', b'"input_tokens":99,', 1)
    assert len(new) == len(old) and new[:256] != old[:256]
    with open(transcript_path(root, "s4"), "r+b") as handle:
        handle.write(new)
    from tests.python.reader_state import fixture_subagents

    fixture_subagents.apply_phase2(root)
