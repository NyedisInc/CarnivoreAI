#!/usr/bin/env python3
"""Measure the current tip against the plan's performance targets.

THIS IS THE HARNESS THE REST OF docs/webui-performance-and-session-menu-plan.md
IS JUDGED AGAINST. It is spec item 1's "establish measurements" half, run
once here to also produce the baseline every later phase is compared to.

WHAT IT MEASURES, against one ISOLATED, real ``src.main:app`` server this
script boots itself (see ``perf_env.PerfServer``) - never the operator's
real installation, never the live ``cloude`` tmux socket:

  - typing echo, proven by xterm's own ``onRender`` paint callback, not a
    parser callback (see ``perf_browser.py``'s module docstring for why
    that distinction is load-bearing here)
  - session entry (launchpad row -> interactive terminal)
  - session switching, cold and warm, unchanged geometry
  - launch (create -> interactive terminal)
  - a menu (the session sidebar's real slide-out panel)
  - settings (the real settings panel)
  - notifications, hook-to-visible-toast (via the app's own documented
    canonical synthetic-toast entry point - see ``PerfClient.create_toast``
    for exactly what is and is not measured by that substitution)
  - archive-scrolling frame times, proxied by the launchpad's own running-
    sessions list at N=50 (see the module docstring section below, "ABOUT
    THE ARCHIVE PROXY", for why)
  - startup, cold (real TOTP login, fresh browser context) and warm
    (reload with a token already held)
  - idle CPU and memory of the server process itself, at each session count

WHY EVERY SESSION IS ``agent_type="shell"``. The plan explicitly requires
measuring "agent startup and external-service latency separately" from
the rest. A bare interactive shell (``AgentsConfig.shell_command``, a
first-class reserved agent type - not a hijacked config override) answers
every keystroke deterministically and in well under a millisecond of its
own compute, with no external API, no token cost, and no run-to-run
variance from a language model's own response time. That isolates
everything this harness's targets are actually about: the browser, the
WebSocket, tmux, and this server's own request handling. A real ``claude``
agent's startup and per-turn latency is a second, clearly separate
question, and is deliberately NOT folded into these numbers - see
``docs/perf-baseline-2026-09-10.md``'s methodology section for how a later
phase can add it as its own opt-in measurement, the same way
``tests/test_led_real_hooks.py`` gates its real-agent run behind
``CLOUDE_REAL_HOOK_TESTS=1``.

WHAT "BROWSER / NETWORK / SUBPROCESS / DATABASE / AGENT TIME" MEANS HERE,
GIVEN THIS SCRIPT MAY NOT EDIT ``src/``. This harness has no server-side
tracing to attribute a single request's time across those five buckets
internally - adding that instrumentation is explicitly out of this file's
fence (three other agents own ``client/`` and ``src/`` tonight). Instead:

  - "browser" and "network+server" are split CLIENT-SIDE, on one clock
    (the page's own ``performance.now()``): the gap from an armed
    interaction to the application's own ``WebSocket.send`` is browser
    input-handling overhead; the gap from that send to the first message
    back is network-plus-server combined (the two cannot be told apart
    without a server-side timestamp); the gap from that message to
    xterm's ``onRender`` is browser render scheduling.
  - "subprocess" is measured OUT OF PROCESS, by counting the server
    pid's live child processes (``perf_client.count_descendants``) across
    an interaction window - every ``tmux`` CLI invocation is a transient
    child of this server, so a nonzero count during a window is direct
    evidence of a subprocess spawned to serve it, independent of any
    internal logging.
  - "database" is measured DIRECTLY against this run's own throwaway
    ``carnivore.db`` (a plain ``SELECT`` timed with a fresh connection,
    scaled to the session count already on that server) rather than
    attributed to one interaction's critical path, because no interaction
    this harness drives is guaranteed to touch the database inline with
    the response the browser is waiting on - see ``_measure_db_cost``.
  - "agent" time is out of scope for the deterministic baseline by
    construction (see above) and is reported as such, not as zero.

ABOUT THE ARCHIVE PROXY. The plan's own evidence table gives the message
archive a 264-361 ms server-side scan cost, but making that number real
would mean synthesizing valid rows in the ``message_*`` schema (hosts,
corpora, projects, transcripts, lines, bodies) or running the real corpus
ingester against fabricated transcript files - either one a correctness
risk to take on inside a performance harness, and out of proportion to
what this file's fence and time budget allow. What is measured instead is
frame-timing (``requestAnimationFrame`` deltas) while programmatically
scrolling the launchpad's OWN real, currently-rendered running-sessions
list at N=50 - real CSS, real DOM, real paint, just not the archive's own
virtualization code. This is reported as a proxy, explicitly, and a real
archive-scroll measurement is named as a follow-up in the baseline doc
rather than silently stood in for.

USAGE

    venv/bin/python3 scripts/perf/run_baseline.py
    venv/bin/python3 scripts/perf/run_baseline.py --sessions 1,10,50
    venv/bin/python3 scripts/perf/run_baseline.py --quick   # smoke-sized

Every run is self-contained: it boots its own server on a free port at or
above 5001, its own throwaway tmux socket, and tears both down (plus every
temp directory) in a ``finally``, whatever happens.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from perf_client import PerfClient, cpu_seconds, sample_process, wait_until  # noqa: E402
from baseline_phases import TOAST_COUNT_JS, BaselineRun, run_browser_phases  # noqa: E402,F401
from perf_env import PerfServer  # noqa: E402
from perf_stats import fmt_ms, idle_cpu_percent, summarize, verdict  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.db import db_path_for  # noqa: E402

PLAN_TARGETS_MS = {
    "typing_echo_total": 50.0,
    "session_switch_warm": 200.0,
    "menu_open": 16.7,
    "notification_toast": 100.0,
}


class DbMissing(RuntimeError):
    pass


def _measure_db_cost(state_dir: Path, session_count: int) -> float:
    db_path = db_path_for(state_dir)
    if not db_path.exists():
        raise DbMissing(f"expected the throwaway server's database at {db_path}")
    t0 = time.perf_counter()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
    finally:
        conn.close()
    return (time.perf_counter() - t0) * 1000.0


IDLE_WINDOW_S = 10.0


def _idle_sample(pid: int, seconds: float = IDLE_WINDOW_S) -> dict:
    empty = {"cpu_percent": None, "rss_kb": None, "child_count": None}
    try:
        cpu_start, wall_start = cpu_seconds(pid), time.monotonic()
        time.sleep(seconds)
        cpu_end, wall_end = cpu_seconds(pid), time.monotonic()
        cpu_percent = idle_cpu_percent(cpu_start, cpu_end, wall_end - wall_start)
    except (RuntimeError, ValueError):
        return empty
    sample = sample_process(pid)
    if sample is None:
        return empty
    return {
        "cpu_percent": cpu_percent,
        "rss_kb": sample.rss_kb,
        "child_count": sample.child_count,
    }


def _start_background_sessions(server: PerfServer, client: PerfClient, n_sessions: int, run_tag: str) -> None:
    background_ids = []
    for i in range(max(0, n_sessions - 2)):
        body = client.create_session(server.work_dir, f"perf-bg-{run_tag}-{i}")
        background_ids.append(body["id"])
    wait_until(lambda: len(client.list_sessions()) >= len(background_ids), timeout=30.0)


def _measure_in_browser(perf_browser: ModuleType, result: dict, quick: bool, run_tag: str, server: PerfServer, client: PerfClient) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-mock-keychain"])
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            perf_browser.install_instrumentation(context)
            run = BaselineRun(result=result, quick=quick, run_tag=run_tag, server=server, client=client,
                              pb=perf_browser, context=context, page=context.new_page())
            run_browser_phases(run)
            context.close()
        finally:
            browser.close()


def run_for_session_count(n_sessions: int, quick: bool = False) -> dict:
    import perf_browser

    result: dict = {"n_sessions": n_sessions, "quick": quick}
    run_tag = uuid.uuid4().hex[:8]
    with PerfServer() as server:
        server.start()
        result["boot_seconds"] = server.boot_seconds
        client = PerfClient(server.base_url, server.totp_secret)
        client.login()
        result["idle_at_zero_sessions"] = _idle_sample(server.pid, seconds=IDLE_WINDOW_S)
        _start_background_sessions(server, client, n_sessions, run_tag)
        result["idle_at_n_sessions"] = _idle_sample(server.pid, seconds=IDLE_WINDOW_S)
        result["db_read_ms_at_n"] = _measure_db_cost(Path(server._state_dir), n_sessions)
        _measure_in_browser(perf_browser, result, quick, run_tag, server, client)
        result["idle_final"] = _idle_sample(server.pid, seconds=IDLE_WINDOW_S)
        client.close()
    return result


def run_stamp() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short=10", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    return f"{datetime.now(timezone.utc).date().isoformat()} at {rev or 'unknown'}"


def build_report(all_results: list[dict]) -> tuple[str, str]:
    lines: list[str] = []
    stamp = run_stamp()
    lines.append(f"# Performance baseline, {stamp}")
    lines.append("")
    lines.append(
        "Measured against the current tip with "
        "`venv/bin/python3 scripts/perf/run_baseline.py`, one isolated "
        "server per session count, throwaway tmux socket, `CLOUDE_TEST_MODE=1`, "
        "`agent_type=shell` for every session (no real `claude` binary, no "
        "LLM turns - see the harness module docstring for why)."
    )
    lines.append("")
    lines.append(
        "Reproduce with: `venv/bin/python3 scripts/perf/run_baseline.py "
        "--sessions " + ",".join(str(r["n_sessions"]) for r in all_results) + "`"
    )
    lines.append("")
    lines.append("## Plan targets")
    lines.append("")
    lines.append("| Interaction | Target | " + " | ".join(f"N={r['n_sessions']} p95 / verdict" for r in all_results) + " |")
    lines.append("|---|---|" + "---|" * len(all_results))

    def _lookup(r: dict, key_path: str):
        node = r
        for part in key_path.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        if node is None:
            return []
        values = node if isinstance(node, list) else [node]
        return [v for v in values if v is not None]

    def pct_of(all_results, key_path):
        return [summarize(_lookup(r, key_path)) for r in all_results]

    def target_row(label: str, key_path: str, target: float) -> str:
        pcts = pct_of(all_results, key_path)
        cells = [f"{fmt_ms(p.p95)} / {verdict(p.p95, target)} (n={p.n})" for p in pcts]
        return f"| {label} | <= {target} ms | " + " | ".join(cells) + " |"

    lines.append(target_row("Deterministic terminal echo (warm)", "typing_warm.total", PLAN_TARGETS_MS["typing_echo_total"]))
    lines.append(target_row("Warm switch, unchanged geometry", "session_switch_warm_ms", PLAN_TARGETS_MS["session_switch_warm"]))
    lines.append(target_row("Menu open (cold)", "menu_open_cold_ms", PLAN_TARGETS_MS["menu_open"]))
    lines.append(target_row("Local hook to visible toast", "notification_toast", PLAN_TARGETS_MS["notification_toast"]))
    lines.append("")

    lines.append("## Full measurements (p50 / p95 / p99, ms)")
    lines.append("")
    lines.append("| Interaction | " + " | ".join(f"N={r['n_sessions']}" for r in all_results) + " |")
    lines.append("|---|" + "---|" * len(all_results))

    def full_row(label: str, key_path: str) -> str:
        cells = []
        for r in all_results:
            p = summarize(_lookup(r, key_path))
            cells.append(f"{fmt_ms(p.p50)} / {fmt_ms(p.p95)} / {fmt_ms(p.p99)} (n={p.n})")
        return f"| {label} | " + " | ".join(cells) + " |"

    for label, key_path in [
        ("typing echo - dispatch to ws-send (browser), cold", "typing_cold.dispatch_to_send"),
        ("typing echo - ws-send to first byte back (network+server), cold", "typing_cold.send_to_recv"),
        ("typing echo - first byte to onRender (browser render), cold", "typing_cold.recv_to_render"),
        ("typing echo - total, cold", "typing_cold.total"),
        ("typing echo - dispatch to ws-send (browser), warm", "typing_warm.dispatch_to_send"),
        ("typing echo - ws-send to first byte back (network+server), warm", "typing_warm.send_to_recv"),
        ("typing echo - first byte to onRender (browser render), warm", "typing_warm.recv_to_render"),
        ("typing echo - total, warm", "typing_warm.total"),
        ("session entry (launchpad row -> interactive)", "entry_cold_ms"),
        ("session switch, cold", "session_switch_cold_ms"),
        ("session switch, warm (unchanged geometry)", "session_switch_warm_ms"),
        ("launch, cold (create -> interactive)", "launch_cold_ms"),
        ("launch, warm", "launch_warm_ms"),
        ("menu open, cold", "menu_open_cold_ms"),
        ("menu open, warm", "menu_open_warm_ms"),
        ("settings open, cold", "settings_open_cold_ms"),
        ("settings open, warm", "settings_open_warm_ms"),
        ("notification: hook to visible toast", "notification_toast"),
        ("archive-scroll proxy: frame gap (launchpad list, requestAnimationFrame)", "scroll_frame_gaps_ms"),
        ("startup, cold (real TOTP login)", "startup_cold_ms"),
        ("startup, warm (reload, token held)", "startup_warm_ms"),
    ]:
        lines.append(full_row(label, key_path))
    lines.append("")

    lines.append("## Server resources and boot")
    lines.append("")
    lines.append("| | " + " | ".join(f"N={r['n_sessions']}" for r in all_results) + " |")
    lines.append("|---|" + "---|" * len(all_results))
    lines.append(
        "| boot time (process start to /health 200) | "
        + " | ".join(f"{r['boot_seconds']:.2f} s" for r in all_results)
        + " |"
    )
    for label, key in [
        ("idle CPU % (0 sessions)", "idle_at_zero_sessions"),
        ("idle CPU % (N sessions, no viewer)", "idle_at_n_sessions"),
        ("idle CPU % (after full run)", "idle_final"),
    ]:
        cells = []
        for r in all_results:
            v = (r.get(key) or {}).get("cpu_percent")
            cells.append(f"{v:.1f}%" if v is not None else "n/a")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for label, key in [
        ("RSS, MB (0 sessions)", "idle_at_zero_sessions"),
        ("RSS, MB (N sessions, no viewer)", "idle_at_n_sessions"),
        ("RSS, MB (after full run)", "idle_final"),
    ]:
        cells = []
        for r in all_results:
            v = (r.get(key) or {}).get("rss_kb")
            cells.append(f"{v / 1024.0:.1f} MB" if v is not None else "n/a")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    cells = []
    for r in all_results:
        v = r.get("db_read_ms_at_n")
        cells.append(fmt_ms(v))
    lines.append("| direct DB read (`SELECT COUNT(*) FROM sessions`), fresh connection | " + " | ".join(cells) + " |")
    lines.append("")

    doc = "\n".join(lines) + "\n"

    todo_lines = [f"### Performance baseline, {stamp}"]
    for r in all_results:
        typing_p95 = summarize(r.get("typing_warm", {}).get("total") or []).p95
        switch_p95 = summarize([r.get("session_switch_warm_ms")] if r.get("session_switch_warm_ms") is not None else []).p95
        toast_p95 = summarize(r.get("notification_toast") or []).p95
        todo_lines.append(
            f"- N={r['n_sessions']}: typing echo warm p95 {fmt_ms(typing_p95)}, "
            f"warm switch {fmt_ms(switch_p95)}, toast {fmt_ms(toast_p95)}, "
            f"boot {r['boot_seconds']:.2f}s. Full table: the report this run wrote"
        )
    todo_summary = "\n".join(todo_lines) + "\n"

    return doc, todo_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", default="1,10,50", help="comma-separated session counts")
    parser.add_argument("--quick", action="store_true", help="collapse repetition counts for a fast smoke run")
    parser.add_argument("--out", required=True, help="where to write the markdown report")
    parser.add_argument("--raw-json", required=True, help="where to write the raw measurements")
    args = parser.parse_args()

    counts = [int(x) for x in args.sessions.split(",") if x.strip()]
    all_results = []
    for n in counts:
        print(f"=== measuring N={n} sessions (quick={args.quick}) ===", file=sys.stderr)
        result = run_for_session_count(n, quick=args.quick)
        all_results.append(result)

    doc, todo_summary = build_report(all_results)
    Path(args.out).write_text(doc)
    Path(args.raw_json).write_text(json.dumps(all_results, indent=2))
    print(doc)
    print("--- TODO.md summary ---", file=sys.stderr)
    print(todo_summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
