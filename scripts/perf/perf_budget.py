
from __future__ import annotations

from typing import Optional

BUDGET_MAX_LOAD_1M = 4.0
BURST_CAVEAT = "WS frame gap, not pane paint"

UNMEASURED = (
    ("echo p95 at loadavg about 10", "needs the control-mode input path and a loaded run; budget mode refuses above load 4"),
    ("warm open to interactive terminal p50", "needs a browser or Electron run (G2 harness), not this WS-only harness"),
    ("boot REST calls per page load", "needs a browser page load to count calls"),
    ("engine idle cpu at 30 sessions", "harness runs 1 idle session, the budget says 30"),
)
TRACKED = ("key-to-onRender end to end", "decoded JS bytes at boot", "renderer memory per full pane")


def _ok(res: Optional[dict]) -> bool:
    return bool(res) and not res.get("error") and bool(res.get("measured"))


def _line(item: str, value: Optional[float], ceiling: float, unit: str, note: str = "") -> str:
    if value is None:
        return f"{item}: not measured (no samples)"
    verdict = "pass" if value <= ceiling else "fail"
    return f"{item}: {value:g} {unit} <= {ceiling:g} {unit} {verdict}{note}"


def budget_lines(results: dict) -> list[str]:
    k, b = results.get("keystroke"), results.get("burst")
    c = results.get("boot")
    kv = k if _ok(k) else {}
    out = [_line("echo p50", kv.get("p50_ms"), 8.0, "ms"),
           _line("echo p95", kv.get("p95_ms"), 16.0, "ms")]
    if _ok(b):
        gap, closes = b.get("longest_gap_ms"), b.get("overflow_closes")
        if gap is None or closes is None:
            out.append("50 MB burst stall: not measured (no samples)")
        else:
            verdict = "pass" if gap <= 250.0 and closes == 0 else "fail"
            out.append(f"50 MB burst stall: {gap:g} ms <= 250 ms, 4429 closes {closes} <= 0 {verdict} ({BURST_CAVEAT})")
    else:
        out.append("50 MB burst stall: not measured (no samples)")
    out.append(_line("cold engine boot", c.get("health_median_s") if _ok(c) else None, 2.5, "s"))
    out += [f"{name}: not measured ({why})" for name, why in UNMEASURED]
    out += [f"{name}: tracked, no target, not measured" for name in TRACKED]
    return out


def budget_exit_code(lines: list[str]) -> int:
    targeted = [ln for ln in lines if "tracked, no target" not in ln]
    return 0 if targeted and all(ln.endswith("pass") or " pass (" in ln for ln in targeted) else 1
