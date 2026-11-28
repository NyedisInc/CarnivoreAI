
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = str(REPO / "scripts" / "perf" / "mesh_session_cost.py")
sys.path.insert(0, str(REPO / "scripts" / "perf"))
_spec = importlib.util.spec_from_file_location("mesh_session_cost", SCRIPT)
cost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cost)

SMOKE = ["--smoke", "--idle-seconds", "3", "--listing-runs", "20", "--setup-seconds", "60"]


def _run(out: Path, *args: str) -> dict:
    done = subprocess.run([sys.executable, SCRIPT, *args, *SMOKE, "--out", str(out)], capture_output=True, text=True, timeout=150, check=False)
    assert out.exists(), done.stderr[-800:]
    record = json.loads(out.read_text())
    assert "error" not in record, record["error"]
    return record


def test_the_cost_script_runs_emits_every_budget_row_and_can_go_red(tmp_path):
    base = _run(tmp_path / "none.json", "--mode", "none", "--peers", "0", "--rows", "20")
    mesh = _run(tmp_path / "mesh.json", "--mode", "mesh", "--peers", "2", "--rows", "20")
    table = subprocess.run([sys.executable, SCRIPT, "--table", str(tmp_path / "none.json"), str(tmp_path / "mesh.json")], capture_output=True, text=True, timeout=30, check=False)
    assert "smoke, not a result" in table.stdout
    for name in cost.BUDGET:
        found = re.findall(rf"^\| {re.escape(name)} \| (pass|fail|not measured|rerun when quiet) \|", table.stdout, re.M)
        assert len(found) == 1, (name, table.stdout[-1500:])
    assert (mesh["sessions"], mesh["connected"], mesh["followers"], mesh["event_clients"], mesh["shadow_rows"]) == (2, 2, 2, 2, 40), mesh
    assert mesh["hops"]["hop1"]["inside"]["n"] > 0 and mesh["hops"]["hop2"]["inside"]["n"] > 0
    assert mesh["import_counts"]["full"] + mesh["import_counts"]["fast"] > 0 and mesh["wrong_row_counts"] == 0 and base["wrong_row_counts"] == 0
    row = re.search(r"^\| listing import p95 \| (\w[\w ]*) \|", table.stdout, re.M)
    if row.group(1) == "not measured":
        assert mesh["import_full"]["n"] == 0
    assert "| listing import p95, fast path | context |" in table.stdout and "| full imports in the armed window | context |" in table.stdout
    assert "## VERDICT" in table.stdout and table.stdout.rstrip().endswith("these rows do not pass")
    mixed = {**mesh, "load_before": [1.0, 1.0, 1.0], "load_after": [1.0, 1.0, 1.0], "import_full": {"p95": 45.0, "n": 10}, "import_fast": {"p95": 0.5, "n": 500}}
    assert {v["row"]: v for v in cost.evaluate(mixed, [base, base])}["listing import p95"]["word"] == "fail"
    none_full = {**mixed, "import_full": {"p95": None, "n": 0}}
    assert {v["row"]: v for v in cost.evaluate(none_full, [base, base])}["listing import p95"]["word"] == "not measured"
    slow = _run(tmp_path / "slow.json", "--mode", "mesh", "--peers", "2", "--rows", "20", "--slow-listing-ms", "150")
    loaded = {v["row"]: v for v in cost.evaluate(slow, [base, base])}
    assert loaded["listing pass p50 delta"]["word"] in ("fail", "rerun when quiet"), loaded["listing pass p50 delta"]
    quiet = {v["row"]: v for v in cost.evaluate({**slow, "load_before": [1.0, 1.0, 1.0], "load_after": [1.0, 1.0, 1.0]}, [base, base])}
    assert quiet["listing pass p50 delta"]["word"] == "fail", quiet["listing pass p50 delta"]


def test_the_serve_probe_runs_and_its_rows_reach_the_table(tmp_path):
    serve = _run(tmp_path / "serve.json", "--mode", "serve", "--peers", "2", "--rows", "20")
    res = serve["serve"]
    assert min(res["frames"]) >= 1 and res["cpu_pct"] is not None and res["attached"] == 2
    table = subprocess.run([sys.executable, SCRIPT, "--table", str(tmp_path / "serve.json")], capture_output=True, text=True, timeout=30, check=False)
    for name in ("serve: feed cpu", "serve: loop drift max"):
        assert re.search(rf"^\| {re.escape(name)} \| (pass|fail|not measured|rerun when quiet) \|", table.stdout, re.M), table.stdout[-1200:]
    assert "SYNTHETIC" in table.stdout
    assert cost.serve_rows({**serve, "serve": {**res, "frames": [0, 3]}})[0]["word"] == "not measured"


def test_the_verdict_reads_the_latest_record_and_a_missing_one_never_passes():
    def mesh(peers, rows, members, started, p95):
        return {"mode": "mesh", "peers": peers, "rows": rows, "members": members, "started": started, "load_before": [1.0], "load_after": [1.0]}
    rec = mesh(8, 10, "busy", "2026-11-22T10:00:00", 1.0)
    assert cost.latest_by_config([rec, {**rec, "started": "2026-11-22T11:00:00"}, {**rec, "started": "2026-11-22T09:00:00"}])[cost.config_key(rec)]["started"] == "2026-11-22T11:00:00"
    lines, ok = cost.verdict_section([])
    assert not ok and lines[-2] == "these rows do not pass"


def test_a_diagnostic_record_never_counts_for_the_verdict_or_the_baseline():
    def rec(mode, peers, rows, started, rss_kb, diagnostic):
        full = {"mode": mode, "peers": peers, "rows": rows, "members": "busy", "started": started, "load_before": [1.0], "load_after": [1.0], "rev": "x", "tree_dirty": False,
                "shadow_rows": peers * rows, "sessions": peers, "connected": peers, "followers": peers, "event_clients": peers, "requests_total": 9, "requests_per_minute": 9.0,
                "idle_seconds": 60, "idle": {"rss_kb_end": rss_kb, "rss_samples": 9, "cpu_pct": 0.5}, "listing": {"p50": 0.1, "p95": 0.2, "n": 5}}
        return {**full, "diagnostic": diagnostic} if diagnostic else full
    records = [rec("none", 0, 10, "2026-11-22T10:00:00", 250000, []), rec("none", 0, 10, "2026-11-22T10:05:00", 250000, []),
               rec("mesh", 8, 500, "2026-11-22T11:00:00", 500000, []),
               rec("none", 0, 10, "2026-11-22T12:00:00", 1000, ["trace"]),
               rec("mesh", 8, 500, "2026-11-22T12:05:00", 250100, ["trace"])]
    assert cost.config_key(records[2]) != cost.config_key(records[4])
    assert cost.latest_by_config(records)[cost.config_key(records[2])] is records[2]
    text, ok = cost.render_table(records)
    assert not ok and "DIAGNOSTIC trace: not a budget record" in text
    real = re.search(r"^\| rss delta \| fail \| ([\d.]+) MB", text, re.M)
    assert real and abs(float(real.group(1)) - (500000 - 250000) / 1024.0) < 0.01, text[-1500:]
    verdict = text.split("## VERDICT", 1)[1]
    assert "DIAGNOSTIC" not in verdict



def test_a_full_diagnostic_set_never_fills_the_required_slots_of_the_verdict():
    def rec(mode, peers, rows, members, started, rss_kb, diagnostic):
        inside = {"p50": 0.5, "p95": 1.0, "n": 50}
        full = {"mode": mode, "peers": peers, "rows": rows, "members": members, "started": started, "load_before": [1.0, 1.0, 1.0], "load_after": [1.0, 1.0, 1.0], "rev": "x", "tree_dirty": False,
                "shadow_rows": peers * rows, "sessions": peers, "connected": peers, "followers": peers, "event_clients": peers, "requests_total": 9, "requests_per_minute": 9.0,
                "idle_seconds": 60, "idle": {"rss_kb_end": rss_kb, "rss_samples": 9, "cpu_pct": 0.5}, "listing": {"p50": 0.1, "p95": 0.2, "n": 50},
                "drift_during_import": {"max_ms": 1.0, "n": 50}, "import_full": {"p95": 1.0, "n": 50}, "hops": {"hop1": {"inside": inside}, "hop2": {"inside": inside}}, "hop_limiter_full": 0}
        return {**full, "diagnostic": diagnostic} if diagnostic else full
    base = [rec("none", 0, 10, "busy", "2026-11-22T10:0%d:00" % i, 250000, []) for i in range(2)]
    real = [rec("mesh", 8, 10, "busy", "2026-11-22T11:00:00", 250100, []), rec("mesh", 8, 10, "quiet", "2026-11-22T11:01:00", 250100, []), rec("mesh", 32, 10, "busy", "2026-11-22T11:02:00", 250100, [])]
    diag = [rec("mesh", p, 10, w, "2026-11-22T12:0%d:00" % i, 250100, ["product_gc"]) for i, (p, w) in enumerate(((8, "busy"), (8, "quiet"), (32, "busy"), (32, "quiet")))]
    diag.append(rec("mesh", 16, 500, "busy", "2026-11-22T12:09:00", 250100, ["drop_listing"]))
    assert not any(v["word"] != "pass" for v in cost.evaluate(diag[0], base)), "the diagnostic set must be a passing one, or the test proves nothing"
    text, ok = cost.render_table(base + real + diag)
    verdict = text.split("## VERDICT", 1)[1]
    assert not ok and "these rows do not pass" in verdict and "mesh 32x10 quiet: no record" in verdict
    assert "16 peers x 500" not in verdict and "product_gc" not in verdict
    lines, ok_direct = cost.verdict_section([("t", r, cost.evaluate(r, base)) for r in real + diag[:4]])
    assert not ok_direct and "mesh 32x10 quiet: no record" in "\n".join(lines)
    text_all, ok_all = cost.render_table(base + real + diag[:3] + [rec("mesh", 32, 10, "quiet", "2026-11-22T11:03:00", 250100, [])])
    assert ok_all and "every row passes at 8x10 and 32x10" in text_all
