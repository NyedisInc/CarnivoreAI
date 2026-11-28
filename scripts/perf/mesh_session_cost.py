#!/usr/bin/env python3
"""What member links cost one computer (P20 slice 5d-2, ``docs/pack-mesh.md`` "Cost of member links"): one configuration per call, foreground.

    mesh_session_cost.py --mode none|mesh|star|serve --peers N --rows R [--idle-seconds S] [--listing-runs K] --out FILE.json
                         [--slow-listing-ms MS] [--quiet-members] [--smoke]
    mesh_session_cost.py --table FILE.json...      markdown budget table and a VERDICT; exit 1 unless every budget row of the LATEST real record of each
                                                   configuration reads pass (serve records: see mesh_serve_probe.py, synthetic view)

The parent makes N+2 identities, starts the measured process M (``mesh_cost_roles.py --role m``) and, in mesh mode, the simulator S (``--role s``),
issues the signed computer list ONCE as the alpha and hands the byte-identical wire to both, then waits for M's result. Everything runs on isolated
state folders under one temp root, binds 127.0.0.1 port 0 and uses no tmux at all. A row that could not be measured reads "not measured (reason)",
never "pass" (gotcha 11). ``BUDGET`` below was written before the first run and is never edited after one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "perf"))
sys.path.insert(0, str(REPO))

BUDGET: Dict[str, Dict[str, Any]] = {
    "listing pass p50 delta": {"unit": "ms", "8": 20.0, "32": 60.0},
    "listing pass p95 delta": {"unit": "ms", "8": 60.0, "32": 150.0},
    "loop stall during a listing import (max drift)": {"unit": "ms", "8": 50.0, "32": 50.0},
    "listing import p95": {"unit": "ms", "8": 30.0, "32": 30.0},
    "idle cpu delta (median sub-window)": {"unit": "% of one core", "8": 2.0, "32": 6.0},
    "rss delta": {"unit": "MB", "8": 40.0, "32": 120.0},
    "hop 1 (token check) p50": {"unit": "ms", "8": 3.0, "32": 3.0},
    "hop 1 (token check) p95": {"unit": "ms", "8": 15.0, "32": 15.0},
    "hop 2 (grant read) p50": {"unit": "ms", "8": 3.0, "32": 3.0},
    "hop 2 (grant read) p95": {"unit": "ms", "8": 15.0, "32": 15.0},
    "threadpool queueing (submits that found the limiter full)": {"unit": "submits", "8": 0.0, "32": 0.0},
}
LOAD_LIMIT = 10.0
LOAD_RETRY_SECONDS, LOAD_WAIT_SECONDS = 30.0, 600.0
ALPHA_PORT = 47000


def sh(cmd: List[str], timeout: float = 20.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def machine_class() -> str:
    return f"{sh(['sysctl', '-n', 'machdep.cpu.brand_string']) or 'unknown cpu'}, {sh(['sysctl', '-n', 'hw.ncpu']) or '?'} cores"


def load_triplet() -> List[float]:
    return [float(x) for x in re.findall(r"[\d.]+", sh(["sysctl", "-n", "vm.loadavg"]))[:3]]


def load_gate() -> List[float]:
    end = time.time() + min(float(os.environ.get("MESHCOST_LOAD_WAIT_SECONDS", LOAD_WAIT_SECONDS)), LOAD_WAIT_SECONDS)
    while True:
        load = load_triplet()
        if (load and load[0] <= LOAD_LIMIT) or time.time() >= end:
            return load
        time.sleep(LOAD_RETRY_SECONDS)


def make_plan(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    from src.core.computers.tls_identity import ensure_link_identity
    from src.core.relay_identity.device_key import DeviceKey, b64url

    def who(name: str) -> Dict[str, Any]:
        seed = hashlib.sha256(f"meshcost/{name}".encode()).digest()
        folder = root / name
        folder.mkdir(mode=0o700)
        key = DeviceKey.from_seed(seed)
        ensure_link_identity(key, f"mc-{name}", folder)
        return {"name": name, "iid": f"mc-{name}", "seed": seed.hex(), "dir": str(folder), "pub": b64url(key.raw_pub)}

    members = [who(f"m{i + 1:02d}") for i in range(args.peers)]
    return {"root": str(root), "mode": args.mode, "peers": args.peers, "rows": args.rows, "idle_seconds": args.idle_seconds, "listing_runs": args.listing_runs,
            "slow_ms": args.slow_listing_ms, "quiet": bool(args.quiet_members), "setup_seconds": args.setup_seconds, "alpha": who("a"), "m": who("m"), "members": members,
            "trace": bool(args.trace), "product_gc": bool(args.product_gc), "switch_interval": args.switch_interval, "drop_listing": bool(args.drop_listing)}


def issue_lists(plan: Dict[str, Any], ports: Dict[str, int]) -> Dict[str, Any]:
    from src.core.computers.tls_identity import ensure_link_identity
    from src.core.pack.machines import capabilities, roster_doc

    import mesh_cost_roles as roles

    capabilities.MESH_BUILD_ON = True
    alpha = plan["alpha"]
    pack = roles.make_pack(alpha["iid"], "a", roles.key_for(alpha["seed"]), alpha["iid"], alpha["pub"], Path(plan["root"]) / "alpha_cfg.json")
    inputs = []
    for who in [alpha, plan["m"], *plan["members"]]:
        ident = ensure_link_identity(roles.key_for(who["seed"]), who["iid"], Path(who["dir"]))
        inputs.append(roster_doc.RosterInput(install_id=who["iid"], label=who["name"], fed_public_key=who["pub"], cert=ident.cert.der, next_cert=None,
                                             addresses=("127.0.0.1",), link_port=ports.get(who["name"], ALPHA_PORT), relay_id=None,
                                             capabilities=tuple(roles.caps_list())))
    word = pack.custody.refresh_roster(inputs)
    wire = pack.custody.roster_v2_wire()
    if not word.startswith("bump:") or wire is None:
        raise RuntimeError(f"the alpha did not issue a list ({word!r})")
    return {"v2": wire, "alpha": alpha["iid"], "capabilities": capabilities.CAP_MESH}


def child_env(state: Path) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CARNIVORE", "CLOUDE"))}
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    env["CARNIVORE_STATE_DIR"] = str(state)
    env["CARNIVORE_APP_VERSION"] = app_version()
    return env


def app_version() -> str:
    return str(json.loads((REPO / "macOS" / "package.json").read_text())["version"])


def spawn(role: str, plan_path: Path, root: Path) -> subprocess.Popen:
    log = open(root / f"{role}.log", "w")
    return subprocess.Popen([sys.executable, str(REPO / "scripts" / "perf" / "mesh_cost_roles.py"), "--role", role, "--plan", str(plan_path)],
                            cwd=str(REPO), env=child_env(root / f"{role}_state"), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def stop(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=wait)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            continue


def wait_json(path: Path, seconds: float, alive: List[subprocess.Popen]) -> Optional[Any]:
    end = time.time() + seconds
    while time.time() < end:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except ValueError:
                pass
        if any(p.poll() is not None for p in alive) and not path.exists():
            return None
        time.sleep(0.25)
    return None


def log_tail(root: Path, role: str) -> str:
    try:
        lines = [ln[:160] for ln in (root / f"{role}.log").read_text().splitlines() if "Error" in ln or "Traceback" in ln or ln.startswith(" ")]
        return " | ".join(lines[-8:])[-900:]
    except OSError:
        return ""


def sim_cpu(root: Path, start: float, end: float) -> Optional[Dict[str, Any]]:
    try:
        points = [json.loads(line) for line in (root / "s_cpu.jsonl").read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    inside = [p for p in points if start - 2.5 <= p["t"] <= end + 2.5]
    if len(inside) < 2 or inside[-1]["t"] <= inside[0]["t"]:
        return None
    pct = 100.0 * (inside[-1]["cpu"] - inside[0]["cpu"]) / (inside[-1]["t"] - inside[0]["t"])
    return {"cpu_pct": pct, "saturated": pct > 90.0}


def run_serve(root: Path, args: argparse.Namespace, children: List[subprocess.Popen], record: Dict[str, Any]) -> None:
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps({"root": str(root), "peers": args.peers, "rows": args.rows, "idle_seconds": args.idle_seconds}))
    plan_path.chmod(0o600)
    log = open(root / "serve.log", "w")
    children.append(subprocess.Popen([sys.executable, str(REPO / "scripts" / "perf" / "mesh_serve_probe.py"), "--plan", str(plan_path)], cwd=str(REPO),
                                     env=child_env(root / "serve_state"), stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
    result = wait_json(root / "serve_result.json", args.idle_seconds + 120, children)
    if result is None:
        raise RuntimeError("the serve probe wrote no result: " + log_tail(root, "serve"))
    record["serve"] = result


def run_config(args: argparse.Namespace) -> Dict[str, Any]:
    sys.path.insert(0, str(REPO / "scripts" / "perf"))
    lock_taken, load_before = False, load_triplet()
    if not args.smoke:
        import renderer_states

        load_before = load_gate()
        renderer_states.take_lock("mesh_session_cost", 600)
        lock_taken = True
    root = Path(tempfile.mkdtemp(prefix="meshcost", dir="/tmp"))
    os.environ["CARNIVORE_STATE_DIR"] = str(root / "parent_state")
    (root / "parent_state").mkdir(mode=0o700)
    children: List[subprocess.Popen] = []
    t0 = time.time()
    record: Dict[str, Any] = {"budget": BUDGET, "rev": sh(["git", "-C", str(REPO), "rev-parse", "HEAD"]), "machine": machine_class(), "python": sys.version.split()[0],
                              "load_before": load_before, "mode": args.mode, "peers": args.peers, "rows": args.rows, "idle_seconds": args.idle_seconds,
                              "listing_runs": args.listing_runs, "smoke": bool(args.smoke), "slowed": args.slow_listing_ms > 0, "members": "quiet" if args.quiet_members else "busy",
                              "tree_dirty": bool(sh(["git", "-C", str(REPO), "status", "--porcelain", "--", "src", "scripts", "tests"])),
                              "slow_listing_ms": args.slow_listing_ms, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "diagnostic": diagnostic_knobs(args)}
    try:
        if args.mode == "serve":
            run_serve(root, args, children, record)
        else:
            import mesh_cost_roles as roles

            plan = make_plan(root, args)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan))
            plan_path.chmod(0o600)
            rows = roles.build_rows("mc-bytes", min(50, max(1, args.rows)))
            record["bytes_per_row"] = round(sum(len(json.dumps(r)) for r in rows) / len(rows), 1)
            if args.mode != "star":
                if args.mode == "mesh" and args.peers > 0:
                    children.append(spawn("s", plan_path, root))
                children.append(spawn("m", plan_path, root))
                ports: Dict[str, int] = {}
                ready_m = wait_json(root / "ready_m.json", 150, [children[-1]])
                ready_s = wait_json(root / "ready_s.json", 150, children[:-1]) if len(children) > 1 else {}
                if ready_m is None or ready_s is None:
                    raise RuntimeError("a child did not become ready: " + log_tail(root, "m") + " || " + log_tail(root, "s"))
                ports = {"m": ready_m["port"], **ready_s}
                lists = issue_lists(plan, ports)
                tmp = root / "lists.tmp"
                tmp.write_text(json.dumps(lists))
                tmp.replace(root / "lists.json")
            else:
                children.append(spawn("m", plan_path, root))
            budget_wait = args.setup_seconds + args.idle_seconds + args.listing_runs * 0.2 + 120
            result = wait_json(root / "m_result.json", budget_wait, [children[-1]])
            if result is None:
                raise RuntimeError("M wrote no result: " + log_tail(root, "m"))
            record.update(result)
            idle = result.get("idle") or {}
            if args.mode == "mesh" and args.peers > 0 and idle.get("wall_start"):
                record["simulator"] = sim_cpu(root, idle["wall_start"], idle["wall_end"])
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"[:700]
    finally:
        for child in children:
            stop(child)
        if not os.environ.get("MESHCOST_KEEP"):
            shutil.rmtree(root, ignore_errors=True)
        else:
            print("kept", root)
        if lock_taken:
            import renderer_states

            renderer_states.release_lock()
    record["load_after"] = load_triplet()
    record["wall_seconds"] = round(time.time() - t0, 1)
    return record


def column(peers: int) -> str:
    return "8" if peers <= 8 else "32"


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def population_gap(rec: Dict[str, Any]) -> Optional[str]:
    n, r = rec["peers"], rec["rows"]
    if "error" in rec:
        return "the run failed: " + rec["error"][:120]
    if rec.get("wrong_row_counts"):
        return f"for_caller returned the wrong row count {rec['wrong_row_counts']} times"
    if rec.get("shadow_rows") != n * r:
        return f"shadow rows {rec.get('shadow_rows')} not {n * r}"
    if rec["mode"] == "star":
        return None
    for key, label in (("sessions", "sessions"), ("connected", "connected links"), ("followers", "followers"), ("event_clients", "event clients")):
        if rec.get(key) != n:
            return f"{label} {rec.get(key)} not {n}"
    if n > 0 and (not rec.get("requests_total") or (rec.get("idle_seconds", 0) >= 60 and not rec.get("requests_per_minute"))):
        return "requests per minute is 0 with peers up"
    return None


def raw_values(rec: Dict[str, Any]) -> Dict[str, Tuple[Optional[float], int, bool]]:
    idle, hops = rec.get("idle") or {}, rec.get("hops") or {}
    listing, drift = rec.get("listing") or {}, rec.get("drift_during_import") or {}
    path = rec.get("import_path")
    if "import_full" in rec:
        imp = rec["import_full"] or {}
    else:
        imp = (rec.get("import_poll") if path == "poll" else rec.get("import_push")) or {}
    rss = idle.get("rss_kb_end")
    out: Dict[str, Tuple[Optional[float], int, bool]] = {
        "listing pass p50 delta": (listing.get("p50"), listing.get("n", 0), True),
        "listing pass p95 delta": (listing.get("p95"), listing.get("n", 0), True),
        "loop stall during a listing import (max drift)": (drift.get("max_ms"), drift.get("n", 0), False),
        "listing import p95": (imp.get("p95"), imp.get("n", 0), False),
        "idle cpu delta (median sub-window)": (idle.get("cpu_pct"), 5 if idle.get("cpu_pct") is not None else 0, True),
        "rss delta": (rss / 1024.0 if rss else None, idle.get("rss_samples", 0) if rss else 0, True),
    }
    for label, key in (("hop 1 (token check)", "hop1"), ("hop 2 (grant read)", "hop2")):
        inside = (hops.get(key) or {}).get("inside") or {}
        out[f"{label} p50"] = (inside.get("p50"), inside.get("n", 0), False)
        out[f"{label} p95"] = (inside.get("p95"), inside.get("n", 0), False)
    full = rec.get("hop_limiter_full")
    out["threadpool queueing (submits that found the limiter full)"] = (float(full) if full is not None else None, (hops.get("hop1") or {}).get("inside", {}).get("n", 0), False)
    return out


def evaluate(rec: Dict[str, Any], baselines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    col, gap, rows = column(rec["peers"]), population_gap(rec), []
    values = raw_values(rec)
    base_values = [raw_values(b) for b in baselines if population_gap(b) is None]
    for name, spec in BUDGET.items():
        value, count, is_delta = values[name]
        limit = spec[col]
        note, shown = "", value
        if gap:
            note = gap
        elif count == 0 or value is None:
            note = "no full import in the armed window" if name == "listing import p95" and "import_full" in rec else "no samples"
        elif is_delta:
            means = [_mean([bv[name][0] for bv in base_values if bv[name][0] is not None])]
            if len(base_values) < 2 or means[0] is None:
                note = "a 0-peer baseline record is missing"
            else:
                shown = value - means[0]
        if note:
            rows.append({"row": name, "word": "not measured", "value": None, "limit": limit, "margin": None, "unit": spec["unit"], "note": note})
            continue
        margin = limit - shown
        rows.append({"row": name, "word": "pass" if shown <= limit else "fail", "value": shown, "limit": limit, "margin": margin, "unit": spec["unit"], "note": ""})
    return _quiet_words(rec, rows)


LATENCY_ROWS = ("listing pass p50 delta", "listing pass p95 delta", "loop stall during a listing import (max drift)", "listing import p95",
                "hop 1 (token check) p50", "hop 1 (token check) p95", "hop 2 (grant read) p50", "hop 2 (grant read) p95")


def _quiet_words(rec: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    load = max([x[0] for x in (rec.get("load_before"), rec.get("load_after")) if x] or [0.0])
    by = {r["row"]: r for r in rows}
    steady = all(by[n]["word"] == "pass" for n in ("idle cpu delta (median sub-window)", "hop 1 (token check) p50", "hop 2 (grant read) p50"))
    if load > LOAD_LIMIT and steady:
        for name in LATENCY_ROWS:
            if by[name]["word"] == "fail":
                by[name]["word"] = "rerun when quiet"
                by[name]["note"] = f"one-minute load {load:.1f} above {LOAD_LIMIT:.0f}"
    return rows


def context_line(rec: Dict[str, Any]) -> str:
    def cell(part: Dict[str, Any], key: str) -> str:
        value = part.get(key)
        return "n/a" if value is None else f"{value:.2f}"

    hops, drift = rec.get("hops") or {}, rec.get("drift_during_import") or {}
    parts = []
    for key in ("hop1", "hop2"):
        h = hops.get(key) or {}
        parts.append(f"{key} queue p50/p95 {cell(h.get('queue') or {}, 'p50')}/{cell(h.get('queue') or {}, 'p95')} ms, total p50/p95 {cell(h.get('total') or {}, 'p50')}/{cell(h.get('total') or {}, 'p95')} ms")
    gc = rec.get("gc_gen2") or {}
    imp = (rec.get("import_counts") or {}).get(rec.get("import_path") or "", 0)
    parts.append(f"drift p99/max {cell(drift, 'p99')}/{cell(drift, 'max_ms')} ms over {drift.get('n', 0)} samples; armed imports {imp}")
    parts.append(f"gen2 gc {gc.get('count', 'n/a')} pauses, max {gc.get('max_ms', 0.0):.1f} ms, at the worst drift: {'yes' if gc.get('at_worst_drift') else 'no'}")
    parts.extend(split_context(rec))
    return "context: " + "; ".join(parts)


def split_context(rec: Dict[str, Any]) -> List[str]:
    def num(value: Any, fmt: str = ".2f") -> str:
        return "n/a" if value is None else format(value, fmt)

    out = []
    for key, h in sorted((rec.get("hop_split") or {}).items()):
        over, clear = h.get("overlap") or {}, h.get("clear") or {}
        out.append(f"{key} inside p95 over a write lock {num(over.get('p95'))} ms (n {over.get('n', 0)}), clear of one {num(clear.get('p95'))} ms (n {clear.get('n', 0)}), wait p95 {num(h.get('wait_p95'))} ms, cpu p50/p95 {num((h.get('cpu') or {}).get('p50'))}/{num((h.get('cpu') or {}).get('p95'))} ms")
    locks, sync = rec.get("locks") or {}, rec.get("sync_ms") or {}
    out.append(f"write locks {locks.get('count', 'n/a')} (held p95 {num(locks.get('held_p95'))} ms, wait p95 {num(locks.get('wait_p95'))} ms); sync_peer p50/p95 {num(sync.get('p50'))}/{num(sync.get('p95'))} ms")
    held = rec.get("held_bytes") or {}
    out.append("held " + ", ".join(f"{k.split('.')[-1]} {v.get('bytes', 0) / 1e6:.1f} MB" for k, v in sorted(held.items())) if held else "held n/a")
    return out


def diagnostic_knobs(args: argparse.Namespace) -> List[str]:
    return sorted(k for k, on in (("trace", args.trace), ("product_gc", args.product_gc), ("switch_interval", args.switch_interval is not None), ("drop_listing", args.drop_listing)) if on)


def config_key(rec: Dict[str, Any]) -> Tuple[Any, ...]:
    return (rec["mode"], rec["peers"], rec["rows"], rec.get("members", "busy"), bool(rec.get("smoke")), bool(rec.get("slowed")), tuple(rec.get("diagnostic") or ()))


def latest_by_config(records: List[Dict[str, Any]]) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    out: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for rec in records:
        key = config_key(rec)
        if key not in out or str(rec.get("started", "")) >= str(out[key].get("started", "")):
            out[key] = rec
    return out


def serve_rows(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    col, res = column(rec["peers"]), rec.get("serve") or {}
    gap = None
    if "error" in rec or not res:
        gap = "the run failed: " + str(rec.get("error", "no result"))[:120]
    elif res.get("attached") != rec["peers"] or res.get("streams_end") != rec["peers"]:
        gap = f"attached streams {res.get('attached')} (at the end {res.get('streams_end')}) not {rec['peers']}"
    elif not res.get("frames") or min(res["frames"]) < 1:
        gap = "a socket drained 0 frames"
    specs = (("serve: feed cpu", "idle cpu delta (median sub-window)", res.get("cpu_pct")),
             ("serve: loop drift max", "loop stall during a listing import (max drift)", (res.get("drift") or {}).get("max_ms")))
    rows = []
    for name, budget, value in specs:
        limit, unit = BUDGET[budget][col], BUDGET[budget]["unit"]
        if gap or value is None:
            rows.append({"row": name, "word": "not measured", "value": None, "limit": limit, "margin": None, "unit": unit, "note": gap or "no samples"})
        else:
            rows.append({"row": name, "word": "pass" if value <= limit else "fail", "value": value, "limit": limit, "margin": limit - value, "unit": unit, "note": ""})
    load = max([x[0] for x in (rec.get("load_before"), rec.get("load_after")) if x] or [0.0])
    if load > LOAD_LIMIT and rows[0]["word"] == "pass" and rows[1]["word"] == "fail":
        rows[1]["word"], rows[1]["note"] = "rerun when quiet", f"one-minute load {load:.1f} above {LOAD_LIMIT:.0f}"
    return rows


def _row_line(v: Dict[str, Any]) -> Tuple[str, bool]:
    if v["word"] == "not measured":
        return f"| {v['row']} | not measured | ({v['note']}) | {v['limit']} {v['unit']} | |", False
    if v["word"] == "rerun when quiet":
        return f"| {v['row']} | rerun when quiet | {v['value']:.2f} {v['unit']} | {v['limit']} {v['unit']} | ({v['note']}) |", False
    verb = "pass by" if v["word"] == "pass" else "fail by"
    return f"| {v['row']} | {v['word']} | {v['value']:.2f} {v['unit']} | {v['limit']} {v['unit']} | {verb} {abs(v['margin']):.2f} {v['unit']} |", v["word"] == "pass"


def _verdict_text(v: Dict[str, Any]) -> str:
    if v["value"] is None:
        return f"{v['word']} ({v['note']}); limit {v['limit']} {v['unit']}"
    margin = f"{'passes by' if v['margin'] >= 0 else 'fails by'} {abs(v['margin']):.2f} {v['unit']}"
    return f"{v['word']}: value {v['value']:.2f} {v['unit']}, limit {v['limit']} {v['unit']}, {margin}" + (f" ({v['note']})" if v["note"] else "")


def render_table(records: List[Dict[str, Any]]) -> Tuple[str, bool]:
    records = sorted(records, key=lambda r: str(r.get("started", "")))
    bases = {s: [r for r in records if r["mode"] == "none" and r["peers"] == 0 and r.get("smoke", False) == s and not r.get("slowed") and not r.get("diagnostic")] for s in (False, True)}
    latest = latest_by_config(records)
    latest_ids = {id(r) for r in latest.values()}
    lines: List[str] = []
    counted: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]] = []
    for rec in records:
        history = "" if id(rec) in latest_ids or rec["mode"] == "none" else " (HISTORY: a later record of this configuration exists, the verdict reads that one)"
        meta = f"rev {str(rec.get('rev'))[:10]}, tree dirty: {'yes' if rec.get('tree_dirty') else 'no'}; started {rec.get('started')}; load {rec.get('load_before')} to {rec.get('load_after')}"
        if rec["mode"] == "none":
            idle, listing = rec.get("idle") or {}, rec.get("listing") or {}
            lines += [f"### baseline, 0 peers{history}", "", f"{meta}; listing p50 {listing.get('p50')} ms, p95 {listing.get('p95')} ms; idle cpu {idle.get('cpu_pct')} %; rss end {idle.get('rss_kb_end')} KB", ""]
            continue
        if rec["mode"] not in ("mesh", "serve"):
            continue
        smoke = (" (smoke, not a result)" if rec.get("smoke") else "") + (" (SLOWED red check)" if rec.get("slowed") else "") + (f" (DIAGNOSTIC {', '.join(rec['diagnostic'])}: not a budget record)" if rec.get("diagnostic") else "")
        if rec["mode"] == "serve":
            tag = f"serve {rec['peers']} sockets x {rec['rows']} rows"
            res = rec.get("serve") or {}
            lines += [f"### {tag} (synthetic view){smoke}{history}", "", f"{meta}",
                      "The view is SYNTHETIC (no database, not peer_listing.for_caller) and the cpu figure is the WHOLE probe process (driver and drain tasks included): an over-count of the feed alone.", "",
                      "| row | verdict | value | limit | margin |", "|---|---|---|---|---|"]
            verdicts = serve_rows(rec)
            context = (f"context: frames per socket {res.get('frames')}, full frames per socket {res.get('full_frames')}, bytes {res.get('bytes')}, attached {res.get('attached')} "
                       f"(at the end {res.get('streams_end')}), rss max {res.get('rss_kb_max')} KB, drift p99 {(res.get('drift') or {}).get('p99')} ms")
        else:
            tag = f"mesh {rec['peers']} peers x {rec['rows']} rows ({rec.get('members', 'busy')} members)"
            lines += [f"### {tag}{smoke}{history}", "", f"{meta}; import path: {rec.get('import_path')}; bytes per row: {rec.get('bytes_per_row')}", "",
                      "| row | verdict | value | limit | margin |", "|---|---|---|---|---|"]
            verdicts = evaluate(rec, bases[bool(rec.get("smoke"))])
            context = context_line(rec)
        passed = True
        for v in verdicts:
            line, one = _row_line(v)
            lines.append(line)
            passed = passed and one
        if rec["mode"] == "mesh":
            fast, fulls = rec.get("import_fast"), (rec.get("import_full") or {}).get("n")
            if fast is not None:
                lines.append(f"| listing import p95, fast path | context | {'n/a' if fast.get('p95') is None else format(fast['p95'], '.2f')} ms (n {fast.get('n', 0)}) | not judged | |")
                lines.append(f"| full imports in the armed window | context | {fulls} | not judged | |")
        lines += ["", context, ""]
        if id(rec) in latest_ids and not rec.get("smoke") and not rec.get("slowed") and not rec.get("diagnostic"):
            counted.append((tag, rec, verdicts))
    stars = [r for r in records if r["mode"] == "star"]
    if stars:
        lines += ["### star comparison (row driven, no verdict)", "", "| peers x rows | import path | listing pass p50 delta ms | p95 ms | import p95 ms | loop stall max ms |", "|---|---|---|---|---|---|"]
        for r in stars:
            vals = raw_values(r)
            star_tag = f" (DIAGNOSTIC {', '.join(r['diagnostic'])}: not a budget record)" if r.get("diagnostic") else ""
            cells = [vals[k][0] for k in ("listing pass p50 delta", "listing pass p95 delta", "listing import p95", "loop stall during a listing import (max drift)")]
            lines.append(f"| {r['peers']} x {r['rows']}{star_tag} | {r.get('import_path')} | " + " | ".join("n/a" if c is None else f"{c:.2f}" for c in cells) + " |")
        lines.append("")
    base = bases[False] or bases[True]
    if base:
        listing = [b["listing"]["p50"] for b in base if b.get("listing")]
        cpu = [b["idle"]["cpu_pct"] for b in base if b.get("idle") and b["idle"].get("cpu_pct") is not None]
        lines.append(f"0-peer baselines: {len(base)} runs; listing p50 {', '.join(f'{x:.2f}' for x in listing)} ms; idle cpu {', '.join(f'{x:.2f}' for x in cpu)} %")
        lines.append("")
    verdict_lines, ok = verdict_section(counted)
    return "\n".join(lines + verdict_lines), ok


REQUIRED = (("mesh", 8, 10, "busy"), ("mesh", 8, 10, "quiet"), ("mesh", 32, 10, "busy"), ("mesh", 32, 10, "quiet"))


def verdict_section(counted: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]) -> Tuple[List[str], bool]:
    lines = ["## VERDICT", ""]
    have = {(r["mode"], r["peers"], r["rows"], r.get("members", "busy")) for _, r, _ in counted if not r.get("diagnostic")}
    missing = [f"{m} {p}x{r} {w}" for m, p, r, w in REQUIRED if (m, p, r, w) not in have]
    ten_ok = not missing
    all_ok = bool(counted) and any(r["mode"] == "mesh" for _, r, _ in counted)
    for tag, rec, verdicts in counted:
        for v in verdicts:
            passed = v["word"] == "pass"
            all_ok = all_ok and passed
            if rec["rows"] == 10 and rec["peers"] in (8, 32):
                ten_ok = ten_ok and passed
            if not passed or rec["rows"] >= 500:
                lines.append(f"- {tag}, {v['row']}: {_verdict_text(v)}")
    for name in missing:
        lines.append(f"- {name}: no record (not measured)")
    if len(lines) == 2:
        lines.append("- every row of every latest record passes")
    lines += ["", "every row passes at 8x10 and 32x10" if ten_ok else "these rows do not pass", ""]
    return lines, all_ok and not missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("none", "mesh", "star", "serve"))
    parser.add_argument("--peers", type=int, default=0)
    parser.add_argument("--rows", type=int, default=10)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    parser.add_argument("--listing-runs", type=int, default=200)
    parser.add_argument("--out")
    parser.add_argument("--setup-seconds", type=float, default=150.0)
    parser.add_argument("--slow-listing-ms", type=float, default=0.0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--quiet-members", action="store_true", help="members send only the periodic full frame (no 2 s status flips)")
    parser.add_argument("--trace", action="store_true", help="DIAGNOSTIC: tracemalloc and memory marks at the 0-member and steady states (never a budget record)")
    parser.add_argument("--product-gc", action="store_true", help="DIAGNOSTIC: apply the product's boot gc tuning in M (never a budget record)")
    parser.add_argument("--switch-interval", type=float, default=None, help="DIAGNOSTIC: sys.setswitchinterval in M (never a budget record)")
    parser.add_argument("--drop-listing", action="store_true", help="DIAGNOSTIC: M drops its last listing result before the idle window (never a budget record)")
    parser.add_argument("--table", nargs="+", metavar="FILE")
    args = parser.parse_args()
    if args.table:
        text, ok = render_table([json.loads(Path(p).read_text()) for p in args.table])
        print(text)
        return 0 if ok else 1
    if not args.mode or not args.out or (args.mode == "none" and args.peers != 0):
        parser.error("--mode and --out are required, and --mode none means --peers 0")
    record = run_config(args)
    Path(args.out).write_text(json.dumps(record, indent=1))
    print(json.dumps({k: record.get(k) for k in ("mode", "peers", "rows", "import_path", "setup_seconds", "wall_seconds", "error")}))
    return 1 if "error" in record else 0


if __name__ == "__main__":
    sys.exit(main())
