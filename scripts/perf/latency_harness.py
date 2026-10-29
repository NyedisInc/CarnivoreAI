#!/usr/bin/env python3
"""Terminal latency harness: the before/after yardstick for speed changes.

Output: one JSON document (``--json-out``) plus a short summary on stdout.
EXIT CODE: 0 only when every selected metric produced samples; 1 when any
selected metric measured nothing (a check that looked at nothing must not
pass); 2 in --budget mode when the 1-minute loadavg is over 4 (or unreadable)
before or after the run: "could not measure", never a pass.

Example:
    venv/bin/python3 scripts/perf/latency_harness.py --json-out run.json
    venv/bin/python3 scripts/perf/latency_harness.py --only keystroke --keys 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from perf_budget import BUDGET_MAX_LOAD_1M, budget_exit_code, budget_lines  # noqa: E402
from perf_stats import fmt_ms, summarize  # noqa: E402

METRICS = ("keystroke", "burst", "idle_cpu", "boot")
OVERFLOW_CLOSE_CODE = 4429
KEY_ALPHABET = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BURST_BYTES = 50 * 1024 * 1024


def longest_gap_ms(arrivals: Sequence[float]) -> Optional[float]:
    if len(arrivals) < 2:
        return None
    return max(b - a for a, b in zip(arrivals, arrivals[1:])) * 1000.0


def parse_cputime(text: str) -> float:
    parts = text.strip().split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"not a cputime: {text!r}")
    total = 0.0
    for part in parts:
        total = total * 60.0 + float(part)
    return total


def idle_cpu_percent(cpu_start_s: float, cpu_end_s: float, wall_s: float) -> float:
    if wall_s <= 0 or cpu_end_s < cpu_start_s:
        raise ValueError("bad idle window")
    return (cpu_end_s - cpu_start_s) / wall_s * 100.0


def read_loadavg_1m() -> Optional[float]:
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def exit_code(results: dict, selected: Sequence[str]) -> int:
    if not selected:
        return 1
    for name in selected:
        res = results.get(name)
        if not res or res.get("error") or not res.get("measured"):
            return 1
    return 0


def _cpu_seconds(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "cputime=", "-p", str(pid)],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"ps could not read pid {pid}")
    return parse_cputime(out.stdout)


class Terminal:

    def __init__(self, base_url: str, token: str, session_id: str) -> None:
        self.url = base_url.replace("http", "ws", 1) + f"/ws/terminal?session_id={session_id}"
        self.token = token
        self.ws = None
        self.buf = bytearray()
        self.frames: list[tuple[float, int]] = []
        self.close_code: Optional[int] = None
        self.resyncs = 0
        self.ready = asyncio.Event()
        self.changed = asyncio.Event()
        self._reader: Optional[asyncio.Task] = None

    async def open(self) -> None:
        import websockets
        self.ws = await websockets.connect(
            self.url, subprotocols=["cloude.jwt.v1", self.token], max_size=None,
            max_queue=None, ping_interval=None)
        self._reader = asyncio.create_task(self._read())
        await asyncio.wait_for(self.ready.wait(), 15)

    async def _read(self) -> None:
        import websockets
        try:
            async for msg in self.ws:
                now = time.perf_counter()
                if isinstance(msg, bytes):
                    self.frames.append((now, len(msg)))
                    self.buf += msg
                    self.changed.set()
                    continue
                try:
                    kind = json.loads(msg).get("type")
                except ValueError:
                    continue
                if kind == "request_dims":
                    await self.ws.send(json.dumps({"type": "pty_resize", "cols": 120, "rows": 40}))
                elif kind == "terminal.ready":
                    self.ready.set()
                elif kind == "terminal.resync":
                    self.resyncs += 1
        except websockets.ConnectionClosed as exc:
            self.close_code = exc.rcvd.code if exc.rcvd else None
        finally:
            self.changed.set()

    async def wait_for(self, needle: bytes, timeout: float) -> bool:
        deadline = time.perf_counter() + timeout
        while needle not in self.buf:
            left = deadline - time.perf_counter()
            if left <= 0 or self.close_code is not None:
                return needle in self.buf
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), left)
            except asyncio.TimeoutError:
                pass
        return True

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)


async def measure_keystroke(term: Terminal, keys: int, warmup: int) -> dict:
    await term.ws.send(b"stty raw -echo; printf 'RE''ADY'; exec cat\r")
    if not await term.wait_for(b"READY", 15):
        return {"error": "pane never reached the echo loop", "measured": 0}
    await asyncio.sleep(0.4)
    samples: list[float] = []
    missed = 0
    for i in range(warmup + keys):
        byte = KEY_ALPHABET[i % len(KEY_ALPHABET)]
        mark = len(term.buf)
        t0 = time.perf_counter()
        await term.ws.send(bytes([byte]))
        deadline = t0 + 2.0
        got = False
        while True:
            if byte in term.buf[mark:]:
                got = True
                break
            left = deadline - time.perf_counter()
            if left <= 0 or term.close_code is not None:
                break
            term.changed.clear()
            try:
                await asyncio.wait_for(term.changed.wait(), left)
            except asyncio.TimeoutError:
                break
        if got:
            arrival = next((t for t, _ in term.frames if t >= t0), time.perf_counter())
            if i >= warmup:
                samples.append((arrival - t0) * 1000.0)
        elif i >= warmup:
            missed += 1
        await asyncio.sleep(0.005)
    pct = summarize(samples)
    return {"measured": pct.n, "missed": missed, "warmup": warmup, "p50_ms": pct.p50,
            "p95_ms": pct.p95, "p99_ms": pct.p99, "max_ms": pct.max_ms,
            "mean_ms": pct.mean_ms}


async def measure_burst(term: Terminal, total_bytes: int, reopen) -> dict:
    cmd = (f"yes 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' "
           f"| head -c {total_bytes}; printf '\\nBURST''DONE\\n'\r")
    start_frames = len(term.frames)
    t0 = time.perf_counter()
    await term.ws.send(cmd.encode())
    arrivals: list[float] = []
    received = overflows = 0
    finished = False
    while True:
        finished = await term.wait_for(b"BURSTDONE", 300)
        arrivals += [t for t, _ in term.frames[start_frames:] if t >= t0]
        received += sum(n for t, n in term.frames[start_frames:] if t >= t0)
        if finished or term.close_code != OVERFLOW_CLOSE_CODE or overflows >= 20:
            break
        overflows += 1
        await term.close()
        term = await reopen()
        start_frames = 0
    t1 = time.perf_counter()
    if not arrivals:
        return {"error": "no frames during burst", "measured": 0}
    last_close = term.close_code
    await term.close()
    return {"measured": len(arrivals), "finished": finished,
            "total_s": round(t1 - t0, 3), "bytes_received": received,
            "longest_gap_ms": longest_gap_ms(arrivals),
            "first_frame_ms": (arrivals[0] - t0) * 1000.0,
            "overflow_closes": overflows, "overflowed": overflows > 0, "resyncs": term.resyncs,
            "final_close_code": last_close}


async def measure_idle_cpu(pid: int, seconds: float) -> dict:
    c0, t0 = _cpu_seconds(pid), time.monotonic()
    await asyncio.sleep(seconds)
    c1, t1 = _cpu_seconds(pid), time.monotonic()
    pct = idle_cpu_percent(c0, c1, t1 - t0)
    return {"measured": 1, "window_s": round(t1 - t0, 1), "cpu_s": round(c1 - c0, 3),
            "cpu_percent_of_core": round(pct, 2)}


def measure_boot(boots: int) -> dict:
    from perf_client import PerfClient
    from perf_env import PerfServer
    health, authed = [], []
    for _ in range(boots):
        with PerfServer() as srv:
            srv.start()
            health.append(srv.boot_seconds)
            client = PerfClient(srv.base_url, srv.totp_secret)
            try:
                client.login()
                client.list_sessions()
                authed.append(time.monotonic() - srv.boot_started_at)
            finally:
                client.close()
    return {"measured": len(health), "health_s": [round(x, 3) for x in health],
            "first_authed_call_s": [round(x, 3) for x in authed],
            "health_median_s": round(sorted(health)[len(health) // 2], 3)}


async def run(args: argparse.Namespace) -> dict:
    from perf_client import PerfClient
    from perf_env import PerfServer
    selected = [m for m in METRICS if args.only in (None, m)]
    results: dict = {}
    live_metrics = [m for m in selected if m != "boot"]
    if live_metrics:
        with PerfServer() as srv:
            srv.start()
            client = PerfClient(srv.base_url, srv.totp_secret)
            try:
                token = client.login()
                async def fresh_terminal(label: str) -> Terminal:
                    sess = client.create_session(srv.work_dir, label)
                    term = Terminal(srv.base_url, token, sess["id"])
                    await term.open()
                    return term
                for name in live_metrics:
                    try:
                        if name == "idle_cpu":
                            term = await fresh_terminal("idle")
                            await asyncio.sleep(3)
                            results[name] = await measure_idle_cpu(srv.pid, args.idle_seconds)
                        else:
                            term = await fresh_terminal(name)
                            sid = term.url.rsplit("=", 1)[1]
                            if name == "keystroke":
                                results[name] = await measure_keystroke(term, args.keys, args.warmup)
                            else:
                                async def reopen(sid=sid):
                                    t = Terminal(srv.base_url, token, sid)
                                    await t.open()
                                    return t
                                results[name] = await measure_burst(term, BURST_BYTES, reopen)
                                continue
                        await term.close()
                    except Exception as exc:  # noqa: BLE001
                        results[name] = {"error": f"{type(exc).__name__}: {exc}", "measured": 0}
            finally:
                client.close()
    if "boot" in selected:
        try:
            results["boot"] = measure_boot(args.boots)
        except Exception as exc:  # noqa: BLE001
            results["boot"] = {"error": f"{type(exc).__name__}: {exc}", "measured": 0}
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=str(HERE)).stdout.strip()
    return {"revision": rev, "machine": platform.platform(), "python": platform.python_version(),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"), "selected": selected, "results": results}


def summary(doc: dict) -> str:
    r, out = doc["results"], [f"latency harness @ {doc['revision']} on {doc['machine']}"]
    k = r.get("keystroke")
    if k and k.get("measured"):
        out.append(f"keystroke n={k['measured']} missed={k['missed']}: p50 {fmt_ms(k['p50_ms'])} "
                   f"p95 {fmt_ms(k['p95_ms'])} p99 {fmt_ms(k['p99_ms'])} max {fmt_ms(k['max_ms'])}")
    b = r.get("burst")
    if b and b.get("measured"):
        out.append(f"burst {b['bytes_received']/1048576:.1f} MB in {b['total_s']} s: longest gap "
                   f"{fmt_ms(b['longest_gap_ms'])} overflow_closes={b['overflow_closes']} "
                   f"resyncs={b.get('resyncs', 0)} finished={b['finished']}")
    c = r.get("idle_cpu")
    if c and c.get("measured"):
        out.append(f"idle cpu {c['cpu_percent_of_core']}% of a core over {c['window_s']} s")
    o = r.get("boot")
    if o and o.get("measured"):
        out.append(f"boot to /health median {o['health_median_s']} s (runs {o['health_s']})")
    for name, res in r.items():
        if res.get("error"):
            out.append(f"{name} FAILED: {res['error']}")
    return "\n".join(out)


def _load_refusal(load: Optional[float], when: str) -> Optional[str]:
    if load is None:
        return f"could not measure: loadavg unreadable ({when} the run)"
    if load > BUDGET_MAX_LOAD_1M:
        return f"could not measure: loadavg {load:.2f} over {BUDGET_MAX_LOAD_1M:g} ({when} the run)"
    return None


def main_budget(args: argparse.Namespace) -> int:
    if args.only:
        print("--budget runs all four metrics and cannot be combined with --only")
        return 1
    before = read_loadavg_1m()
    refusal = _load_refusal(before, "before")
    if refusal:
        print(refusal)
        return 2
    doc = asyncio.run(run(args))
    after = read_loadavg_1m()
    doc["loadavg_1m_before"], doc["loadavg_1m_after"] = before, after
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(doc, indent=2))
    refusal = _load_refusal(after, "after")
    if refusal:
        print(f"tainted: {refusal}")
        return 2
    lines = budget_lines(doc["results"])
    print("\n".join([f"latency budget @ {doc.get('revision', '?')} on {doc.get('machine', '?')}"] + lines))
    return budget_exit_code(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=METRICS, default=None)
    ap.add_argument("--keys", type=int, default=500)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--idle-seconds", type=float, default=60.0)
    ap.add_argument("--boots", type=int, default=3)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--budget", action="store_true",
                    help="print the the budget lines; exit 2 when loadavg is over 4")
    args = ap.parse_args(argv)
    if args.budget:
        return main_budget(args)
    doc = asyncio.run(run(args))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(doc, indent=2))
    print(summary(doc))
    return exit_code(doc["results"], doc["selected"])


if __name__ == "__main__":
    sys.exit(main())
