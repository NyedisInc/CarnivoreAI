#!/usr/bin/env python3
"""Per-window-state CPU / idle-wakeup sampler for the Carnivore desktop app.

Samples the Electron main, renderer, GPU helpers, WindowServer, the Python
server and the tmux server with `top -l`, while osascript drives the window
into one state (focused | blurred | covered | hidden | control | asis).
One JSON record per run lands in --out; a markdown row is printed and appended
to <out>/<label>.rows.md.  `--table <label>` rebuilds the full table from JSON.

stdlib only.  Takes the shared measurement lock for the whole invocation.
"""
import argparse
import json
import os
import re
import select
import signal
import statistics
import subprocess
import sys
import time

LOCK_DIR = os.path.expanduser("~/dev-worktrees/cloudecode/.measure.lock")
LOCK_STALE_S = 30 * 60
LOAD_LIMIT = 8.0
LOAD_WAIT_S = 10 * 60
SUPPORT = os.path.expanduser("~/Library/Application Support/Carnivore")
STATES = ("focused", "blurred", "covered", "hidden", "control")
ROLES = ("renderer", "gpu", "main", "WindowServer", "server", "tmux")
SETTLE_S = 5
COVER_JXA = """
function run(a) {
  ObjC.import('Cocoa');
  var x = +a[0], y = +a[1], w = +a[2], h = +a[3];
  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy(1);
  var screens = $.NSScreen.screens, ph = screens.objectAtIndex(0).frame.size.height, f = screens.objectAtIndex(0).frame;
  var cx = x + w / 2, cy = ph - (y + h / 2);
  for (var i = 0; i < screens.count; i++) {
    var r = screens.objectAtIndex(i).frame;
    if (cx >= r.origin.x && cx < r.origin.x + r.size.width && cy >= r.origin.y && cy < r.origin.y + r.size.height) { f = r; break; }
  }
  var win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(f, 0, 2, false);
  win.backgroundColor = $.NSColor.blackColor;
  win.level = 3;
  win.makeKeyAndOrderFront(null);
  app.activateIgnoringOtherApps(true);
  console.log("cover " + f.origin.x + "," + f.origin.y + " " + f.size.width + "x" + f.size.height);
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(900));
}
"""


def run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def osa(script):
    rc, out, err = run(["timeout", "25", "osascript", "-e", script], timeout=40)
    return rc == 0, (out if rc == 0 else err)


_ROW = re.compile(r"^\s*(\d+)\s+(.*?)\s+([\d.]+)[+-]?\s+(\d+)[+-]?\s+([\d.]+)[+-]?\s*$")


def parse_top(text):
    out = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if m:
            out.append({"pid": int(m.group(1)), "command": m.group(2), "cpu": float(m.group(3)),
                        "idlew": int(m.group(4)), "power": float(m.group(5))})
    return out


def summarize(samples, discard=1):
    kept = samples[discard:]
    if not kept:
        return None
    res = {"n": len(kept)}
    for k in ("cpu", "idlew", "power"):
        v = [s[k] for s in kept]
        res[k] = {"mean": round(statistics.fmean(v), 2), "min": min(v), "max": max(v)}
    return res


def stream_growth(before, after, dt):
    rates = {}
    for path, size in after.items():
        grown = size - before.get(path, size)
        if grown > 0 and dt > 0:
            rates[path] = round(grown / dt, 1)
    return len(rates), rates


def ps_table():
    _, out, _ = run(["ps", "-axo", "pid=,ppid=,etime=,command="])
    rows = []
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) == 4 and p[0].isdigit():
            rows.append((int(p[0]), int(p[1]), p[2], p[3]))
    return rows


def discover(overrides):
    rows = ps_table()
    pids = {}
    main_re = re.compile(r"/Contents/MacOS/(Carnivore|Electron)( |$)")
    mains = [r for r in rows if main_re.search(r[3])]
    if "main" in overrides:
        mains = [r for r in rows if r[0] == overrides["main"]] or mains
    for m in mains:
        kids = [r for r in rows if r[1] == m[0]]
        if any("--type=renderer" in k[3] for k in kids):
            pids["main"] = m[0]
            for k in kids:
                if "--type=renderer" in k[3]:
                    pids.setdefault("renderer", k[0])
                if "--type=gpu-process" in k[3]:
                    pids.setdefault("gpu", k[0])
            for k in rows:
                if k[1] == m[0] and re.search(r"-m src\.main|src/main\.py", k[3]):
                    pids.setdefault("server", k[0])
            break
    if "server" not in pids:
        for r in rows:
            if re.search(r"-m src\.main|Carnivore Menubar/server/src/main\.py", r[3]):
                pids["server"] = r[0]
                break
    _, ws, _ = run(["pgrep", "-x", "WindowServer"])
    if ws:
        pids["WindowServer"] = int(ws.split()[0])
    for r in rows:
        if "tmux -L cloude" in r[3] and "start-server" in r[3]:
            pids["tmux"] = r[0]
            break
    pids.update(overrides)
    return pids, rows


def app_identity(main_pid, rows):
    cmd = next((r[3] for r in rows if r[0] == main_pid), "")
    m = re.match(r"(.*?\.app)/Contents/MacOS/", cmd)
    app = m.group(1) if m else ""
    name = os.path.basename(app)[:-4] if app else "Electron"
    bid = ""
    if app:
        _, bid, _ = run(["plutil", "-extract", "CFBundleIdentifier", "raw", "-o", "-", app + "/Contents/Info.plist"])
    return name, bid or "com.github.Electron"


def take_lock(purpose, wait_s=LOAD_WAIT_S):
    deadline = time.time() + wait_s
    while True:
        rc, _, _ = run(["mkdir", LOCK_DIR])
        if rc == 0:
            with open(os.path.join(LOCK_DIR, "owner"), "w") as f:
                f.write("pid=%d purpose=%s ts=%s\n" % (os.getpid(), purpose, time.strftime("%Y-%m-%dT%H:%M:%S")))
            return
        try:
            age = time.time() - os.path.getmtime(os.path.join(LOCK_DIR, "owner"))
        except OSError:
            age = time.time() - os.path.getmtime(LOCK_DIR)
        if age > LOCK_STALE_S:
            run(["rm", "-rf", LOCK_DIR])
            continue
        if time.time() > deadline:
            sys.exit("measure lock busy: " + open(os.path.join(LOCK_DIR, "owner")).read().strip())
        time.sleep(30)


def release_lock():
    run(["rm", "-rf", LOCK_DIR])


def load1():
    _, out, _ = run(["sysctl", "-n", "vm.loadavg"])
    nums = re.findall(r"[\d.]+", out)
    return float(nums[0]) if nums else 0.0


class LoadGate:
    def __init__(self, wait_s=LOAD_WAIT_S):
        self.budget_end = time.time() + wait_s

    def wait(self):
        while load1() > LOAD_LIMIT and time.time() < self.budget_end:
            time.sleep(15)
        return load1()


class Driver:
    def __init__(self, proc_name, bundle_id):
        self.proc, self.bid = proc_name, bundle_id
        self.opened = set()
        self.cover = None

    def activate(self):
        return osa('tell application id "%s" to activate' % self.bid)

    def _unminimize(self):
        return osa('tell application "System Events" to tell process "%s" to set value of attribute '
                   '"AXMinimized" of every window to false' % self.proc)

    def _bounds(self):
        ok, out = osa('tell application "System Events" to tell process "%s" to get {position, size} of window 1' % self.proc)
        n = [int(float(x)) for x in re.findall(r"-?[\d.]+", out)] if ok else []
        return n if len(n) == 4 else None

    def apply(self, state):
        if state == "focused":
            return self.activate()
        if state == "blurred":
            self.opened.add("Calculator")
            run(["open", "-a", "Calculator"])
            return osa('tell application "Calculator" to activate')
        if state == "covered":
            b = self._bounds() or [0, 0, 1, 1]
            self.cover = subprocess.Popen(
                ["osascript", "-l", "JavaScript", "-e", COVER_JXA, *[str(v) for v in b]],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            ready, _, _ = select.select([self.cover.stdout], [], [], 20)
            line = self.cover.stdout.readline().strip() if ready else ""
            return bool(line), line or "cover window did not start"
        if state == "hidden":
            return osa('tell application "System Events" to set visible of process "%s" to false' % self.proc)
        if state == "control":
            ok, msg = osa('tell application "System Events" to tell process "%s" to set value of attribute '
                          '"AXMinimized" of every window to true' % self.proc)
            if ok:
                return ok, "minimized"
            ok, msg = self.apply("hidden")
            return ok, "hidden fallback: " + msg
        return True, "asis"

    def restore(self):
        if self.cover:
            self.cover.kill()
            self.cover = None
        for app in sorted(self.opened):
            if app == "TextEdit":
                osa('tell application "TextEdit" to close every document saving no')
            osa('tell application "%s" to quit' % app)
        self.opened.clear()
        osa('tell application "System Events" to set visible of process "%s" to true' % self.proc)
        self._unminimize()
        return self.activate()


def pipe_sizes():
    sizes = {}
    try:
        for n in os.listdir(SUPPORT):
            if n.startswith("tmux_") and ".pipe" in n:
                try:
                    sizes[n] = os.path.getsize(os.path.join(SUPPORT, n))
                except OSError:
                    pass
    except OSError:
        pass
    return sizes


def rss_kb(pid):
    _, out, _ = run(["ps", "-o", "rss=", "-p", str(pid)])
    return int(out) if out.strip().isdigit() else None


def sample(pids, n, interval):
    procs = {}
    for role, pid in pids.items():
        procs[role] = subprocess.Popen(
            ["top", "-l", str(n), "-s", str(interval), "-pid", str(pid), "-stats", "pid,command,cpu,idlew,power"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    before, t0 = pipe_sizes(), time.time()
    outs = {r: p.communicate()[0] for r, p in procs.items()}
    after, dt = pipe_sizes(), time.time() - t0
    cnt, rates = stream_growth(before, after, dt)
    return ({r: summarize(parse_top(o)) for r, o in outs.items()},
            {"streaming_files": cnt, "bytes_per_s": rates, "total_bytes_per_s": round(sum(rates.values()), 1)}, dt)


def run_state(state, args, pids, rows, drv, gate, label, displays):
    rec = {"label": label, "state": state, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pids": pids,
           "args": {"samples": args.samples, "interval": args.interval}}
    if state == "asis":
        ok, note = True, "asis"
    else:
        ok, note = drv.apply(state)
    rec["drive"] = {"ok": ok, "note": note}
    if not ok:
        rec["skipped"] = "osascript failed: %s" % note[:200]
        if state != "focused":
            drv.restore()
        return rec
    time.sleep(SETTLE_S)
    rec["load_before"] = gate.wait()
    _, et, _ = run(["ps", "-o", "etime=", "-p", str(pids.get("main", 0))])
    rec["main_uptime"] = et
    rec["rss_kb_before"] = {r: rss_kb(p) for r, p in pids.items()}
    rec["procs"], rec["streaming"], rec["dt_s"] = sample(pids, args.samples, args.interval)
    rec["rss_kb_after"] = {r: rss_kb(p) for r, p in pids.items()}
    rec["load_after"] = load1()
    rec["displays"] = displays
    rec["restore"] = drv.restore()[1] if state != "asis" else ""
    return rec


def displays_summary():
    _, out, _ = run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=60)
    res = []
    try:
        for gpu in json.loads(out).get("SPDisplaysDataType", []):
            for d in gpu.get("spdisplays_ndrvs", []):
                res.append({"name": d.get("_name"), "res": d.get("_spdisplays_resolution") or d.get("spdisplays_resolution"),
                            "main": d.get("spdisplays_main")})
    except ValueError:
        pass
    return res


def _cell(s):
    if not s:
        return "-"
    return "%.1f (%.1f-%.1f) / %.0f" % (s["cpu"]["mean"], s["cpu"]["min"], s["cpu"]["max"], s["idlew"]["mean"])


def md_header():
    return ("| state | uptime | load | streaming | " + " | ".join(ROLES) + " |\n|" + "---|" * (4 + len(ROLES)) + "\n")


def md_row(rec):
    if rec.get("skipped"):
        return "| %s | - | - | - | SKIPPED: %s |" % (rec["state"], rec["skipped"])
    p = rec["procs"]
    return "| %s | %s | %.1f | %d files, %.0f B/s | %s |" % (
        rec["state"], rec.get("main_uptime", "-"), rec.get("load_before", 0), rec["streaming"]["streaming_files"],
        rec["streaming"]["total_bytes_per_s"], " | ".join(_cell(p.get(r)) for r in ROLES))


def table(out_dir, label):
    recs = []
    for n in sorted(os.listdir(out_dir)):
        if n.startswith(label + "-") and n.endswith(".json"):
            recs.append(json.load(open(os.path.join(out_dir, n))))
    order = {s: i for i, s in enumerate(STATES + ("asis",))}
    recs.sort(key=lambda r: (order.get(r["state"], 9), r["ts"]))
    return ("cell = cpu%% mean (min-max) / idle wakeups mean\n\n" + md_header() + "\n".join(md_row(r) for r in recs) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default="focused", help="comma list of %s, asis, or all" % "|".join(STATES))
    ap.add_argument("--out", default=os.environ.get("CARNIVORE_MEASURE_OUT") or os.path.expanduser("~/carnivore-measure"))
    ap.add_argument("--label", default="run")
    ap.add_argument("--samples", type=int, default=14)
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--load-wait", type=int, default=LOAD_WAIT_S, help="max seconds to wait for 1-min load <= %d" % LOAD_LIMIT)
    ap.add_argument("--table", metavar="LABEL", help="print the markdown table for LABEL's JSON files and exit")
    for role in ROLES:
        ap.add_argument("--pid-" + role, type=int, dest="pid_" + role)
    args = ap.parse_args()
    if args.table:
        print(table(args.out, args.table))
        return
    states = list(STATES) if args.state == "all" else args.state.split(",")
    bad = [s for s in states if s not in STATES + ("asis",)]
    if bad:
        sys.exit("unknown state: %s" % bad)
    os.makedirs(args.out, exist_ok=True)
    overrides = {r: getattr(args, "pid_" + r) for r in ROLES if getattr(args, "pid_" + r)}
    pids, rows = discover(overrides)
    missing = [r for r in ROLES if r not in pids]
    if missing:
        print("warning: pids not found for %s" % missing, file=sys.stderr)
    if not pids:
        sys.exit("no processes discovered")
    name, bid = app_identity(pids.get("main", 0), rows)
    drv = Driver(name, bid)
    take_lock("renderer_states " + args.label)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        gate, displays = LoadGate(args.load_wait), displays_summary()
        for st in states:
            rec = run_state(st, args, pids, rows, drv, gate, args.label, displays)
            path = os.path.join(args.out, "%s-%s-%s.json" % (args.label, st, time.strftime("%H%M%S")))
            with open(path, "w") as f:
                json.dump(rec, f, indent=1)
            row = md_row(rec)
            print(row, flush=True)
            with open(os.path.join(args.out, args.label + ".rows.md"), "a") as f:
                f.write(row + "\n")
    finally:
        drv.restore()
        release_lock()


if __name__ == "__main__":
    main()
