
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_VOCAB = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_VERSION = re.compile(r"[A-Za-z0-9_.+-]{1,32}")
_AGY_SENDER_RE = re.compile(
    r"\[Message\]\s+[^\n]*\bsender=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_SIDECAR_BYTES = 64 * 1024
SYNTHETIC = "<synthetic>"
Counts = Tuple[int, int, int, int]
EXTRAS = ("thinking_tokens", "web_searches", "web_fetches", "cache_write_5m_tokens", "cache_write_1h_tokens")


def project_key(cwd: str) -> str:
    return hashlib.sha256(os.path.realpath(os.path.expanduser(cwd)).encode()).hexdigest()[:24]


def path_key(path: str) -> int:
    return int.from_bytes(hashlib.sha256(path.encode()).digest()[:8], "big") >> 1


def branch_hash(branch: str) -> str:
    return hashlib.sha256(branch.encode()).hexdigest()[:16]


def vocab(value: object) -> Optional[str]:
    return value if isinstance(value, str) and _VOCAB.fullmatch(value) else None


def name(value: object) -> str:
    return vocab(value) or "other"


def count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def minute_of(value: object) -> Optional[int]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            return None
        stamp = int(parsed.timestamp())
    except (ValueError, OverflowError, OSError):
        return None
    return stamp // 60 * 60 if 0 <= stamp < 2 ** 62 else None


def sidecar_subagent_type(path: str) -> Optional[str]:
    try:
        with Path(path).with_suffix(".meta.json").open("rb") as handle:
            data = json.loads(handle.read(_SIDECAR_BYTES))
    except (OSError, ValueError):
        return None
    return vocab(data.get("agentType")) if isinstance(data, dict) else None


@dataclass
class Response:

    key: str
    t: int
    model: str
    project: str
    counts: Counts
    extras: Tuple[int, ...]
    stop: Optional[str]

    def dump(self) -> list:
        return [self.key, self.t, self.model, self.project, list(self.counts), list(self.extras), self.stop]

    @classmethod
    def load(cls, raw: Optional[list]) -> Optional["Response"]:
        if not raw:
            return None
        key, t, model, project, counts, extras, stop = raw
        return cls(key, t, model, project, tuple(counts), tuple(extras), stop)


@dataclass
class LineFacts:

    t: int
    project: str
    response: Optional[Response] = None
    codex_delta: Optional[Counts] = None
    counters: List[Tuple[str, str, int]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


def _meta_claude(obj: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    version, branch = obj.get("version"), obj.get("gitBranch")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        out["cli_version"] = version
    if isinstance(branch, str) and branch:
        out["branch_hash"] = branch_hash(branch)
    return out


def claude_line(obj: Mapping[str, Any], offset: int, state: Dict[str, Any]) -> Optional[LineFacts]:
    t = minute_of(obj.get("timestamp"))
    if t is None:
        return None
    cwd = obj.get("cwd")
    facts = LineFacts(t, project_key(cwd) if isinstance(cwd, str) and cwd else "", meta=_meta_claude(obj))
    kind = obj.get("type")
    if kind == "system":
        if isinstance(obj.get("uuid"), str):
            if obj.get("subtype") == "compact_boundary":
                trigger = obj.get("compactMetadata")
                trigger = trigger.get("trigger") if isinstance(trigger, dict) else None
                facts.counters.append(("compactions", name(trigger) if trigger else "", 1))
            elif obj.get("subtype") == "turn_duration":
                facts.counters.append(("turns", "", 1))
        return facts
    message = obj.get("message")
    if kind != "assistant" or not isinstance(message, dict):
        return facts
    usage = message.get("usage")
    if isinstance(usage, dict):
        model = message.get("model") if isinstance(message.get("model"), str) else state.get("model", "")
        counts: Counts = tuple(count(usage.get(k)) for k in (  # type: ignore[assignment]
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
        if not (model == SYNTHETIC and not any(counts)):
            state["model"] = model
            details, server = usage.get("output_tokens_details"), usage.get("server_tool_use")
            cache = usage.get("cache_creation")
            extras = tuple(count(holder.get(f)) if isinstance(holder, dict) else 0 for holder, f in (
                (details, "thinking_tokens"), (server, "web_search_requests"), (server, "web_fetch_requests"),
                (cache, "ephemeral_5m_input_tokens"), (cache, "ephemeral_1h_input_tokens")))
            msg_id = message.get("id")
            stop = message.get("stop_reason")
            facts.response = Response(msg_id if isinstance(msg_id, str) else f"@{offset}", t, model, facts.project,
                                      counts, extras, name(stop) if isinstance(stop, str) else None)
    if state.get("model") == SYNTHETIC:
        return facts
    content = message.get("content")
    for block in content if isinstance(content, list) else ():
        if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("id"), str):
            facts.counters.append(("tool_calls", name(block.get("name")), 1))
    return facts


def codex_line(obj: Mapping[str, Any], state: Dict[str, Any]) -> Optional[LineFacts]:
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    kind, inner = obj.get("type"), payload.get("type")
    meta: Dict[str, Any] = {}
    if kind == "session_meta":
        if isinstance(payload.get("cwd"), str) and payload["cwd"]:
            state["project"] = project_key(payload["cwd"])
        version, git = payload.get("cli_version"), payload.get("git")
        branch = git.get("branch") if isinstance(git, dict) else None
        if isinstance(version, str) and _VERSION.fullmatch(version):
            meta["cli_version"] = version
        if isinstance(branch, str) and branch:
            meta["branch_hash"] = branch_hash(branch)
        if payload.get("thread_source") == "subagent":
            meta["agent_kind"] = "subagent"
            meta["subagent_type"] = vocab(payload.get("agent_role"))
            meta["parent_conversation_id"] = vocab(payload.get("parent_thread_id"))
    if kind == "turn_context" and isinstance(payload.get("model"), str):
        state["model"] = payload["model"]
    t = minute_of(obj.get("timestamp"))
    if t is None:
        return None
    facts = LineFacts(t, state.get("project", ""), meta=meta)
    if kind == "compacted":
        facts.counters.append(("compactions", "", 1))
    elif kind == "event_msg" and inner == "task_complete":
        facts.counters.append(("turns", "", 1))
    elif kind == "response_item" and inner in ("function_call", "custom_tool_call"):
        if isinstance(payload.get("call_id"), str):
            facts.counters.append(("tool_calls", name(payload.get("name")), 1))
    elif kind == "response_item" and inner == "web_search_call":
        facts.counters.append(("web_searches", "", 1))
    elif kind == "event_msg" and inner == "token_count":
        info = payload.get("info")
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        if isinstance(total, dict):
            inclusive, cache_read = count(total.get("input_tokens")), count(total.get("cached_input_tokens"))
            cache_write = count(total.get("cache_write_input_tokens"))
            current = [max(0, inclusive - cache_read - cache_write), cache_write, cache_read,
                       count(total.get("output_tokens"))]
            old = state.get("counts", [0, 0, 0, 0])
            if any(a < b for a, b in zip(current, old)):
                old = [0, 0, 0, 0]
            state["counts"] = current
            delta = tuple(a - b for a, b in zip(current, old))
            if any(delta):
                facts.codex_delta = delta  # type: ignore[assignment]
            reasoning, previous = count(total.get("reasoning_output_tokens")), state.get("reasoning", 0)
            if reasoning < previous:
                previous = 0
            state["reasoning"] = reasoning
            if reasoning > previous:
                facts.counters.append(("thinking_tokens", "", reasoning - previous))
    return facts


def agy_parent_from_record(obj: Mapping[str, Any], self_id: Optional[str] = None) -> Optional[str]:
    if obj.get("type") != "SYSTEM_MESSAGE":
        return None
    content = obj.get("content")
    if not isinstance(content, str) or "sender=" not in content:
        return None
    match = _AGY_SENDER_RE.search(content)
    if not match:
        return None
    parent = match.group(1)
    return None if self_id and parent == self_id else parent


def agy_line(obj: Mapping[str, Any], offset: int, state: Dict[str, Any],
             *, conversation_id: Optional[str] = None) -> Optional[LineFacts]:
    cwd = obj.get("cwd")
    if isinstance(cwd, str) and cwd:
        state["project"] = project_key(cwd)
    t = minute_of(obj.get("created_at"))
    if t is None:
        return None
    project = state.get("project", "")
    meta: Dict[str, Any] = {}
    kind = obj.get("type")
    if kind == "USER_INPUT":
        state["has_user_input"] = True
        facts = LineFacts(t, project, meta=meta)
        facts.counters.append(("turns", "", 1))
        return facts
    if kind == "SYSTEM_MESSAGE" and not state.get("has_user_input") and not state.get("parent_id"):
        parent = agy_parent_from_record(obj, conversation_id)
        if parent:
            state["parent_id"] = parent
            meta["parent_conversation_id"] = parent
            meta["agent_kind"] = "subagent"
    facts = LineFacts(t, project, meta=meta)
    if kind == "CHECKPOINT":
        facts.counters.append(("compactions", "", 1))
        return facts
    if kind != "PLANNER_RESPONSE":
        return facts
    raw_model = obj.get("model")
    model = raw_model if isinstance(raw_model, str) and raw_model else state.get("model", "")
    if model:
        state["model"] = model
    counts: Counts = (
        count(obj.get("input_tokens")),
        count(obj.get("cache_write_tokens")),
        count(obj.get("cache_read_tokens")),
        count(obj.get("output_tokens")),
    )
    if any(counts):
        step_index = obj.get("step_index")
        key = f"step:{step_index}" if isinstance(step_index, int) and not isinstance(step_index, bool) else f"@{offset}"
        facts.response = Response(key, t, model, project, counts, (0,) * len(EXTRAS), None)
    calls = obj.get("tool_calls")
    for call in calls if isinstance(calls, list) else ():
        if isinstance(call, dict) and isinstance(call.get("name"), str) and call["name"]:
            facts.counters.append(("tool_calls", name(call.get("name")), 1))
    return facts
