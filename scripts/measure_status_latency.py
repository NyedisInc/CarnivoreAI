#!/usr/bin/env python3
"""Measure status-light latency and idle CPU on an ISOLATED test server.

WHY THIS EXISTS (issue #762). The attention watcher re-reads every live
session on a fixed tick; the filesystem trigger wakes it early when a
session's registry record, transcript or subagents directory changes. This
script puts a number on both halves: how long a file write takes to reach
a ``session.status_changed`` frame on ``/ws/events``, and what the server
costs in CPU while N sessions sit idle.

HOW. Against a ``scripts/testsrv`` slot (its HOME is the slot's own
``home/``, so the registry and transcripts written here are the only ones
that server reads), it creates N claude-typed sessions WITHOUT starting
claude, then stands in for claude by writing exactly what claude writes:
``~/.claude/sessions/<pane pid>.json`` (rewritten IN PLACE, same inode, as
Claude Code's ``publishDiscipline: "inPlace"`` does) and an appended
``~/.claude/projects/<slug>/<uuid>.jsonl``. Each trial flips one session
and times the first frame carrying the expected status.

SAFETY. It refuses the live ``cloude`` socket and port 8000, and it only
writes under the slot directory it is handed.

Usage:
  venv/bin/python3 scripts/measure_status_latency.py --slot-dir \
      ~/dev-worktrees/.testsrv/slot2 --base http://127.0.0.1:8102 \
      --socket cloude-test2 --sessions 10 --trials 20 --idle-seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
import urllib.request
import uuid as uuidlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import websockets

JWT_SUBPROTOCOL = "cloude.jwt.v1"
CLAUDE_VERSION = "2.1.283"
TRIAL_TIMEOUT_SECONDS = 15.0
STATUS_FRAME = "session.status"


@dataclass
class Fake:

    session_id: str
    tmux_name: str
    pane_id: str
    pane_pid: int
    created: int
    cwd: Path
    conversation: str
    registry: Path
    transcript: Path


def _iso(at: Optional[datetime] = None) -> str:
    at = at or datetime.now(timezone.utc)
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _token(auth_state: Path) -> str:
    state = json.loads(auth_state.read_text())
    items = state["origins"][0]["localStorage"]
    return next(i["value"] for i in items if i["name"] == "claude_tunnel_token")


def _api(base: str, token: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def _tmux(socket: str, *args: str) -> str:
    if socket == "cloude":
        raise SystemExit("refusing the live cloude socket")
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True,
                          text=True, check=True, timeout=10).stdout.strip()


def _slug(path: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in path)


def _write_registry(fake: Fake, status: str, waiting_for: Optional[str] = None) -> None:
    millis = int(time.time() * 1000)
    record = {
        "pid": fake.pane_pid, "sessionId": fake.conversation, "cwd": str(fake.cwd),
        "startedAt": fake.created * 1000, "version": CLAUDE_VERSION,
        "kind": "interactive", "tmux": "%s:@1.%s" % (fake.tmux_name, fake.pane_id),
        "status": status, "updatedAt": millis, "statusUpdatedAt": millis,
    }
    if waiting_for:
        record["waitingFor"] = waiting_for
    mode = "r+" if fake.registry.exists() else "w"
    with open(fake.registry, mode) as handle:
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(record))


def _append(fake: Fake, *records: dict) -> None:
    with open(fake.transcript, "a") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _user(fake: Fake) -> dict:
    return {"type": "user", "isSidechain": False, "timestamp": _iso(),
            "sessionId": fake.conversation, "uuid": str(uuidlib.uuid4()),
            "message": {"role": "user", "content": "go"}}


def _assistant(fake: Fake) -> dict:
    return {"type": "assistant", "isSidechain": False, "timestamp": _iso(),
            "sessionId": fake.conversation, "uuid": str(uuidlib.uuid4()),
            "message": {"role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "done"}]}}


def _turn_end(fake: Fake) -> dict:
    later = datetime.now(timezone.utc) + timedelta(milliseconds=5)
    return {"type": "system", "subtype": "turn_duration", "isSidechain": False,
            "durationMs": 1000, "messageCount": 2, "timestamp": _iso(later),
            "uuid": str(uuidlib.uuid4()), "sessionId": fake.conversation,
            "version": CLAUDE_VERSION, "pendingBackgroundAgents": 0}


def setup(base: str, token: str, socket: str, slot_dir: Path, count: int) -> List[Fake]:
    home = slot_dir / "home"
    registry_dir = home / ".claude" / "sessions"
    registry_dir.mkdir(parents=True, exist_ok=True)
    fakes = []
    for index in range(count):
        cwd = slot_dir / "work" / ("lat%d" % index)
        cwd.mkdir(parents=True, exist_ok=True)
        created = _api(base, token, "POST", "/api/v1/sessions", {
            "project_name": "lat%d" % index, "working_dir": str(cwd),
            "agent_type": "claude", "auto_start_claude": False, "copy_templates": False,
        })
        name = created["tmux_session"]
        epoch, pane_id, pane_pid = _tmux(
            socket, "list-panes", "-t", "=%s:" % name, "-F",
            "#{session_created} #{pane_id} #{pane_pid}").split()
        conversation = str(uuidlib.uuid4())
        project = home / ".claude" / "projects" / _slug(str(cwd))
        project.mkdir(parents=True, exist_ok=True)
        fake = Fake(created["id"], name, pane_id, int(pane_pid), int(epoch), cwd,
                    conversation, registry_dir / ("%s.json" % pane_pid),
                    project / (conversation + ".jsonl"))
        _append(fake, _user(fake), _assistant(fake), _turn_end(fake))
        _write_registry(fake, "idle")
        fakes.append(fake)
    return fakes


class Frames:

    def __init__(self) -> None:
        self.waiters: Dict[str, "asyncio.Future"] = {}
        self.latest: Dict[str, str] = {}

    def expect(self, session_id: str, statuses: tuple) -> "asyncio.Future":
        future = asyncio.get_running_loop().create_future()
        self.waiters[session_id] = (future, statuses)
        return future

    def feed(self, frame: dict) -> None:
        if frame.get("type") != STATUS_FRAME or "activity_status" not in frame:
            return
        session_id = frame["session_id"]
        self.latest[session_id] = frame["activity_status"]
        entry = self.waiters.get(session_id)
        if entry and frame["activity_status"] in entry[1] and not entry[0].done():
            entry[0].set_result(time.monotonic())


async def _listen(base: str, token: str, frames: Frames) -> None:
    url = base.replace("http", "ws", 1) + "/ws/events"
    async with websockets.connect(url, subprotocols=[JWT_SUBPROTOCOL, token],
                                  origin=base, max_size=None) as socket:
        async for text in socket:
            try:
                frames.feed(json.loads(text))
            except (ValueError, KeyError):
                continue


async def _trial(frames: Frames, fake: Fake, kind: str) -> Optional[float]:
    if kind == "working":
        future = frames.expect(fake.session_id, ("working", "working_subagent"))
        start = time.monotonic()
        _append(fake, _user(fake))
        _write_registry(fake, "busy")
    elif kind == "stream":
        future = frames.expect(fake.session_id, ("working", "working_subagent"))
        start = time.monotonic()
        _append(fake, _assistant(fake))
    else:
        future = frames.expect(fake.session_id, ("finished_unread", "idle"))
        start = time.monotonic()
        _append(fake, _assistant(fake), _turn_end(fake))
        _write_registry(fake, "idle")
    try:
        arrived = await asyncio.wait_for(future, TRIAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return None
    return (arrived - start) * 1000.0


def _cpu_seconds(pid: int) -> float:
    text = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True,
                          text=True, check=True).stdout.strip()
    parts = [float(p) for p in text.replace("-", ":").split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def _summary(values: List[Optional[float]]) -> str:
    got = sorted(v for v in values if v is not None)
    misses = len(values) - len(got)
    if not got:
        return "no samples, %d misses" % misses
    p90 = got[min(len(got) - 1, int(round(0.9 * (len(got) - 1))))]
    return "n=%d p50=%.0fms p90=%.0fms max=%.0fms mean=%.0fms misses=%d" % (
        len(got), statistics.median(got), p90, got[-1], statistics.fmean(got), misses)


async def run(args: argparse.Namespace) -> None:
    slot_dir = Path(args.slot_dir).expanduser()
    if args.socket == "cloude" or args.base.rstrip("/").endswith(":8000"):
        raise SystemExit("refusing the live install")
    token = _token(slot_dir / "auth-state.json")
    pid = int(json.loads((slot_dir / "server.pid").read_text())["pid"])
    fakes = setup(args.base, token, args.socket, slot_dir, args.sessions)
    frames = Frames()
    listener = asyncio.create_task(_listen(args.base, token, frames))
    await asyncio.sleep(args.settle_seconds)
    print("settled statuses:", sorted(frames.latest.get(f.session_id, "?") for f in fakes))
    load_before = os.getloadavg()[0]
    cpu0, wall0 = _cpu_seconds(pid), time.monotonic()
    await asyncio.sleep(args.idle_seconds)
    cpu = _cpu_seconds(pid) - cpu0
    wall = time.monotonic() - wall0
    print("idle cpu: %.2fs over %.0fs = %.2f%% of a core (load1 %.2f -> %.2f)" % (
        cpu, wall, 100 * cpu / wall, load_before, os.getloadavg()[0]))
    results: Dict[str, List[Optional[float]]] = {"working": [], "done": [], "stream": [], "stream_done": []}
    rng = random.Random(762)
    for _ in range(args.trials):
        fake = rng.choice(fakes)
        await asyncio.sleep(rng.uniform(0.2, 2.2))
        results["working"].append(await _trial(frames, fake, "working"))
        await asyncio.sleep(rng.uniform(0.2, 2.2))
        results["done"].append(await _trial(frames, fake, "done"))
        await asyncio.sleep(rng.uniform(0.2, 2.2))
        results["stream"].append(await _trial(frames, fake, "stream"))
        await asyncio.sleep(rng.uniform(0.2, 2.2))
        results["stream_done"].append(await _trial(frames, fake, "done"))
    for kind, values in results.items():
        print("latency %-8s %s" % (kind, _summary(values)))
    if args.burst_seconds > 0:
        await _burst(pid, rng.choice(fakes), args.burst_seconds)
    listener.cancel()


async def _burst(pid: int, fake: Fake, seconds: float) -> None:
    cpu0, wall0 = _cpu_seconds(pid), time.monotonic()
    writes = 0
    while time.monotonic() - wall0 < seconds:
        _append(fake, _assistant(fake))
        writes += 1
        await asyncio.sleep(0.02)
    cpu, wall = _cpu_seconds(pid) - cpu0, time.monotonic() - wall0
    print("burst cpu: %d writes over %.0fs, %.2fs cpu = %.2f%% of a core" % (
        writes, wall, cpu, 100 * cpu / wall))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slot-dir", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--idle-seconds", type=float, default=60.0)
    parser.add_argument("--settle-seconds", type=float, default=8.0)
    parser.add_argument("--burst-seconds", type=float, default=0.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
