#!/usr/bin/env python3
"""Generate the SYNTHETIC transcript fixtures of the session timeline slices (T1, T4, T5, T10), deterministically.

Its one job: write small Claude Code transcript files built from scratch (fake ids, fake text, a fixed clock) into
tests/python/fixtures/timeline/, plus MANIFEST.json naming each file's census keys. Nothing here is cut from a real
transcript: the repository has a public export, so a real line must never land in it.

The record shapes come from measurement (docs/timeline.md): the queue sequences, the pasted_content wrapper and the
normalization the transcript applies to tabs, CRLF and trailing blanks are reproduced exactly as T0 measured them.

Usage:
    python3 scripts/timeline/make_fixtures.py [--out DIR] [--check] [--with-oversize]
--check writes nothing and exits 1 when the committed files differ from the generated ones (drift) or the directory
holds a file the generator did not produce, 0 when equal.
--with-oversize also writes oversize_line.jsonl (one 5 MiB line); it is never committed, tests build it on demand.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from census import record_key  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "tests" / "python" / "fixtures" / "timeline"
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
VERSION = "2.1.322"
OVERSIZE_BYTES = 5 * 1024 * 1024
OVERSIZE_NAME = "oversize_line.jsonl"
PASTE_ID = "f1x0"


def sid(n: int) -> str:
    return "b%07d-0000-4000-9000-000000000000" % n

Rec = Dict[str, Any]


class Convo:

    def __init__(self, sid: str, sidechain: bool = False, agent: str = "", uuid_ns: str = "") -> None:
        self.sid, self.side, self.agent = sid, sidechain, agent
        self.ns: str = uuid_ns or sid
        self.n: int = 0
        self.last: Optional[str] = None
        self.records: List[Rec] = []

    def stamp(self) -> str:
        self.n += 1
        return (EPOCH + timedelta(seconds=self.n)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def uid(self) -> str:
        return "%s-0000-4000-8000-%012d" % (self.ns[:8], self.n + 1)

    def add(self, type_: str, chain: bool = True, **fields: Any) -> Rec:
        rec: Rec = {"parentUuid": self.last if chain else None, "isSidechain": self.side, "type": type_,
                    "uuid": self.uid(), "timestamp": self.stamp(), "userType": "external", "entrypoint": "cli",
                    "cwd": "/work/example", "sessionId": self.sid, "version": VERSION, "gitBranch": "main"}
        if self.agent:
            rec["agentId"] = self.agent
        rec.update(fields)
        self.last = rec["uuid"]
        self.records.append(rec)
        return rec

    def bare(self, type_: str, **fields: Any) -> Rec:
        rec: Rec = {"type": type_, **fields, "sessionId": self.sid}
        self.records.append(rec)
        return rec

    def prompt(self, text: Any, **kw: Any) -> Rec:
        return self.add("user", message={"role": "user", "content": text}, origin={"kind": "human"},
                        promptSource="typed", **kw)

    def say(self, blocks: List[Rec], stop: Any = "end_turn") -> Rec:
        return self.add("assistant", message={"role": "assistant", "model": "fixture-model", "content": blocks,
                                              "stop_reason": stop, "usage": {"input_tokens": 1, "output_tokens": 1}})

    def call(self, name: str, call_id: str, **inp: Any) -> Rec:
        return self.say([{"type": "tool_use", "id": call_id, "name": name, "input": inp}], "tool_use")

    def result(self, call_id: str, content: str = "ok") -> Rec:
        return self.add("user", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content}]})

    def turn_end(self, ms: int = 1500) -> Rec:
        return self.add("system", subtype="turn_duration", durationMs=ms, messageCount=2, isMeta=False)

    def queue(self, op: str, content: Any = None) -> Rec:
        rec = self.bare("queue-operation", operation=op, timestamp=self.stamp())
        if content is not None:
            rec["content"] = content
        return rec

    def queued_command(self, text: str, source: str) -> Rec:
        return self.add("attachment", attachment={"type": "queued_command", "prompt": text, "source_uuid": source,
                                                  "commandMode": "prompt", "origin": {"kind": "human"}})


def wrapped(body: str) -> str:
    return '\n\n<pasted_content id="%s">\n%s\n</pasted_content id="%s">\n' % (PASTE_ID, body, PASTE_ID)


def basic_turns() -> List[Rec]:
    c = Convo(sid(1))
    c.bare("mode", mode="normal")
    c.add("attachment", attachment={"type": "hook_success", "hookName": "SessionStart", "exitCode": 0})
    c.add("attachment", attachment={"type": "total_tokens_reminder", "used": 10})
    c.prompt("fixture prompt one")
    c.say([{"type": "thinking", "thinking": "fixture thought"}, {"type": "text", "text": "fixture reply"}], None)
    c.call("Bash", "toolu_f1", command="echo fixture")
    c.result("toolu_f1", "fixture")
    c.say([{"type": "text", "text": "fixture done"}])
    c.add("system", subtype="stop_hook_summary", hookCount=1, hookInfos=[], hookErrors=[], level="info")
    c.turn_end()
    c.bare("ai-title", aiTitle="Fixture title")
    c.prompt("fixture prompt two")
    c.say([{"type": "text", "text": "fixture two"}])
    c.turn_end()
    c.bare("last-prompt", leafUuid=c.last)
    return c.records


def queue_cases() -> List[Rec]:
    c = Convo(sid(2))
    c.prompt("fixture run a long command")
    c.call("Bash", "toolu_q1", command="sleep 1")
    c.queue("enqueue", "fixture queued while busy")
    c.queue("remove", "fixture queued while busy")
    src = c.result("toolu_q1")
    c.queued_command("fixture queued while busy", src["uuid"])
    c.say([{"type": "text", "text": "fixture handled"}])
    c.turn_end()
    c.queue("enqueue", "fixture queued for the next turn")
    c.queue("dequeue")
    c.prompt("fixture queued for the next turn")
    c.say([{"type": "text", "text": "fixture next"}])
    c.turn_end()
    note = "<task-notification><task-id>t1</task-id><status>completed</status></task-notification>"
    c.queue("enqueue", note)
    c.queue("remove", note)
    c.add("user", message={"role": "user", "content": note}, isMeta=False, origin={"kind": "task-notification"})
    c.queue("enqueue", "fixture typed then pulled back")
    c.queue("popAll", "fixture typed then pulled back")
    return c.records


def paste_cases() -> List[Rec]:
    c = Convo(sid(3))
    c.prompt(wrapped("fixture    tabbed\n\nline2   \n\n\nline5      end\nfixture tail."))
    c.say([{"type": "text", "text": "ok"}])
    c.turn_end()
    c.prompt("fixture    tabbed\n\nz fixture")
    c.say([{"type": "text", "text": "ok"}])
    c.turn_end()
    c.prompt("\n   fixture leading")
    c.say([{"type": "text", "text": "ok"}])
    c.turn_end()
    c.prompt("fixture long unwrapped " + "word " * 400)
    c.say([{"type": "text", "text": "ok"}])
    c.turn_end()
    return c.records


def compaction_cases() -> List[Rec]:
    c = Convo(sid(4))
    c.prompt("fixture before compaction")
    c.say([{"type": "text", "text": "ok"}])
    before = c.last
    c.turn_end()
    c.add("system", chain=False, subtype="compact_boundary", content="Conversation compacted", logicalParentUuid=before,
          compactMetadata={"trigger": "auto", "preTokens": 1000, "postTokens": 100, "durationMs": 10}, isMeta=False)
    c.add("user", message={"role": "user", "content": "fixture summary of the conversation"}, isCompactSummary=True)
    c.add("system", subtype="microcompact_boundary", content="micro", isMeta=False)
    c.bare("history-suppression", cause="fixture", ts=c.stamp())
    c.prompt("fixture after compaction")
    c.say([{"type": "text", "text": "ok"}])
    c.turn_end()
    return c.records


def interrupt_cases() -> List[Rec]:
    c = Convo(sid(5))
    c.prompt("fixture interrupted")
    c.say([{"type": "text", "text": "partial"}], None)
    c.prompt("[Request interrupted by user]")
    c.prompt("fixture again")
    c.call("Bash", "toolu_i1", command="sleep 9")
    c.add("user", message={"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user for tool use]"}]})
    c.prompt("fixture long answer")
    c.say([{"type": "text", "text": "cut"}], "max_tokens")
    return c.records


def notice_cases() -> List[Rec]:
    c = Convo(sid(6))
    c.add("system", subtype="api_error", level="error", error={"status": 529, "type": "overloaded"}, retryAttempt=1,
          retryInMs=500.0, maxRetries=3)
    c.add("system", subtype="informational", content="fixture info", isMeta=False, level="info")
    c.add("system", subtype="local_command", content="<command-name>/fixture</command-name>", isMeta=False)
    c.add("user", message={"role": "user", "content": "<command-name>/fixture</command-name>"})
    c.add("system", subtype="scheduled_task_fire", content="fixture fire", taskId="job1", cron="* * * * *", prompt="x")
    c.add("system", subtype="agents_killed", isMeta=False)
    c.add("system", content="fixture raw hook line", isMeta=False)
    return c.records


def rewind_cases() -> List[Rec]:
    c = Convo(sid(7))
    c.prompt("fixture root original")
    c.say([{"type": "text", "text": "abandoned root reply"}])
    c.turn_end()
    c.last = None
    c.prompt("fixture root rewritten")
    c.say([{"type": "text", "text": "kept root reply"}])
    c.turn_end()
    c.prompt("fixture second")
    c.say([{"type": "text", "text": "second reply"}])
    c.turn_end()
    anchor = c.last
    c.prompt("fixture third original")
    c.say([{"type": "text", "text": "abandoned third reply"}])
    c.turn_end()
    c.last = anchor
    c.prompt("fixture third rewritten")
    c.say([{"type": "text", "text": "kept third reply"}])
    c.turn_end()
    return c.records


def switch_cases() -> List[Rec]:
    c = Convo(sid(8))
    c.add("user", message={"role": "user", "content": "fixture inherited"}, forkedFrom={"sessionId": sid(1), "messageUuid": "x"})
    c.prompt("fixture own prompt")
    c.say([{"type": "text", "text": "ok"}])
    c.bare("continued-in", timestamp=c.stamp(), continuedInSessionId=sid(9))
    return c.records


def agent_main() -> List[Rec]:
    c = Convo(sid(10))
    c.prompt("fixture delegate")
    c.call("Agent", "toolu_a1", description="fixture agent", subagent_type="general-purpose", prompt="do it")
    c.result("toolu_a1", "Async agent launched successfully. agentId: a1fixture")
    c.add("attachment", attachment={"type": "task_status", "taskId": "a1fixture", "taskType": "local_agent", "status": "running"})
    c.queue("enqueue", "<task-notification><task-id>a1fixture</task-id><status>completed</status></task-notification>")
    c.queue("dequeue")
    c.add("user", message={"role": "user", "content": "<task-notification><task-id>a1fixture</task-id><status>completed</status></task-notification>"},
          origin={"kind": "task-notification"})
    c.say([{"type": "text", "text": "agent done"}])
    c.turn_end()
    return c.records


def agent_file() -> List[Rec]:
    c = Convo(sid(10), sidechain=True, agent="a1fixture", uuid_ns="c0000010")
    c.prompt("do it")
    c.say([{"type": "text", "text": "agent reply"}])
    c.add("attachment", attachment={"type": "structured_output", "data": {"ok": True}, "toolUseID": "toolu_a1"})
    return c.records


def unknown_kinds() -> List[Rec]:
    c = Convo(sid(11))
    c.add("zz-new-kind", payload="fixture")
    c.add("attachment", attachment={"type": "zz_new_attachment"})
    c.add("system", subtype="zz_new_subtype", isMeta=False)
    return c.records


def delivery_cases() -> List[Rec]:
    c = Convo(sid(13))
    for kind, text in (("channel", "<channel source=\"fixture\">fixture channel delivery</channel>"),
                       ("peer", "thread t-1 msg m-1 fixture peer delivery")):
        c.add("user", message={"role": "user", "content": text}, origin={"kind": kind}, promptSource="system",
              isMeta=True)
        c.say([{"type": "text", "text": "fixture delivery reply"}])
    c.prompt("fixture split prompt")
    message = {"role": "assistant", "model": "fixture-model", "id": "msg_split1", "stop_reason": "end_turn",
               "usage": {"input_tokens": 1, "output_tokens": 1}}
    c.add("assistant", message={**message, "content": [{"type": "thinking", "thinking": "fixture split thought"}]})
    c.add("assistant", message={**message, "content": [{"type": "text", "text": "fixture split answer"}]})
    return c.records


def continue_cases() -> List[Rec]:
    c = Convo(sid(16))
    c.prompt("fixture split tool prompt")
    message = {"role": "assistant", "model": "fixture-model", "id": "msg_split_tool", "stop_reason": "end_turn",
               "usage": {"input_tokens": 1, "output_tokens": 1}}
    c.add("assistant", message={**message, "content": [{"type": "thinking", "thinking": "fixture tool thought"}]})
    c.add("assistant", message={**message, "content": [{"type": "text", "text": "fixture tool answer"}]})
    c.add("assistant", message={**message, "content": [
        {"type": "tool_use", "id": "toolu_c1", "name": "Agent", "input": {"subagent_type": "general-purpose"}}]})
    c.result("toolu_c1", "ok")
    c.add("assistant", message={**message, "id": "msg_after_tool", "content": [{"type": "text", "text": "fixture after"}]})
    c.prompt("fixture max tokens prompt")
    c.add("assistant", message={**message, "id": "msg_cut", "stop_reason": "max_tokens",
                                "content": [{"type": "text", "text": "fixture cut reply"}]})
    c.add("assistant", message={**message, "id": "msg_resumed", "content": [{"type": "text", "text": "fixture resumed"}]})
    c.prompt("fixture last prompt")
    c.say([{"type": "text", "text": "fixture last reply"}])
    return c.records


def meta_cases() -> List[Rec]:
    c = Convo(sid(14))
    for text in ("Continue from where you left off.", "Base directory for this skill: /work/example/skill",
                 "<<autonomous-loop-dynamic>>"):
        c.add("user", message={"role": "user", "content": text}, isMeta=True)
        c.say([{"type": "text", "text": "fixture meta reply"}])
    return c.records


def long_text_cases() -> List[Rec]:
    c = Convo(sid(15))
    c.prompt("fixture long prompt text that no event may copy even in part")
    c.call("Read", "toolu_l1", file_path="/work/example/a.txt")
    c.add("user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_l1", "content": [
        {"type": "text", "text": "fixture long tool result text that no event may copy even in part"}]}]})
    c.say([{"type": "thinking", "thinking": "fixture long thought that no event may copy even in part"},
           {"type": "text", "text": "fixture long reply text that no event may copy even in part"}])
    return c.records


FIXTURES: Dict[str, Tuple[str, Callable[[], List[Rec]]]] = {
    "basic_turns": ("%s.jsonl" % sid(1), basic_turns), "queue_cases": ("%s.jsonl" % sid(2), queue_cases),
    "paste_cases": ("%s.jsonl" % sid(3), paste_cases), "compaction_cases": ("%s.jsonl" % sid(4), compaction_cases),
    "interrupt_cases": ("%s.jsonl" % sid(5), interrupt_cases), "notice_cases": ("%s.jsonl" % sid(6), notice_cases),
    "rewind_cases": ("%s.jsonl" % sid(7), rewind_cases), "switch_cases": ("%s.jsonl" % sid(8), switch_cases),
    "agent_main": ("%s.jsonl" % sid(10), agent_main),
    "agent_sub": ("%s/subagents/agent-a1fixture.jsonl" % sid(10), agent_file),
    "unknown_kinds": ("%s.jsonl" % sid(11), unknown_kinds), "delivery_cases": ("%s.jsonl" % sid(13), delivery_cases),
    "meta_cases": ("%s.jsonl" % sid(14), meta_cases), "long_text_cases": ("%s.jsonl" % sid(15), long_text_cases),
    "continue_cases": ("%s.jsonl" % sid(16), continue_cases),
}


def render(records: List[Rec]) -> str:
    return "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in records)


def generate() -> Dict[str, str]:
    files = {path: render(build()) for path, build in FIXTURES.values()}
    manifest = {name: {"file": path, "records": files[path].count("\n"),
                       "census_keys": sorted({record_key(json.loads(line)) for line in files[path].splitlines()})}
                for name, (path, _build) in FIXTURES.items()}
    files["MANIFEST.json"] = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    return files


def oversize_text() -> str:
    c = Convo(sid(12))
    c.call("Bash", "toolu_o1", command="cat big")
    return render([c.result("toolu_o1", "x" * OVERSIZE_BYTES)])


def unknown_files(out: Path, known: Set[str]) -> List[str]:
    if not out.is_dir():
        return []
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and str(p.relative_to(out)) not in known)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 on drift")
    ap.add_argument("--with-oversize", action="store_true", help="also write the 5 MiB oversize_line.jsonl")
    args = ap.parse_args(argv)
    out, files = Path(args.out), generate()
    if args.with_oversize:
        files[OVERSIZE_NAME] = oversize_text()
    drift = [n for n, t in files.items() if not (out / n).is_file() or (out / n).read_text() != t]
    if args.check:
        stray = unknown_files(out, set(files) | {OVERSIZE_NAME})
        print("fixtures drift: %s" % (", ".join(drift) if drift else "none"))
        print("fixtures unknown files: %s" % (", ".join(stray) if stray else "none"))
        return 1 if drift or stray else 0
    for name in drift:
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[name])
    print("wrote %d of %d files to %s" % (len(drift), len(files), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
