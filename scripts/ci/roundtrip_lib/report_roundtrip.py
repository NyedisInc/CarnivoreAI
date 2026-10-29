#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PASS = "PASS"
FAIL = "FAIL"
CANNOT = "CANNOT_DETERMINE"


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def ordered_steps(run_dir: Path) -> List[Tuple[str, str]]:
    steps = []
    for p in sorted((run_dir / "artifacts").glob("*.step")):
        prefix, _, name = p.stem.partition("-")
        steps.append((prefix, name))
    return steps


def flat_keys(data: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                out.update(flat_keys(v, prefix + k + "."))
            else:
                out[prefix + k] = json.dumps(v, sort_keys=True)
    return out


def diff_configs(before: Any, after: Any) -> Dict[str, List[str]]:
    if before is None or after is None:
        return {"cannot_determine": ["one side of the diff is unreadable"]}
    a, b = flat_keys(before), flat_keys(after)
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    changed = sorted(k for k in a if k in b and a[k] != b[k])
    return {"added": added, "removed": removed, "changed": changed}


def summarise_probe(probe: Optional[dict]) -> Dict[str, Any]:
    if probe is None:
        return {"probe": CANNOT}
    projects = probe.get("projects")
    return {
        "config_loaded": probe.get("auth_config_loadable"),
        "project_count": len(projects) if isinstance(projects, list) else projects,
        "project_names": (
            [p.get("name") for p in projects] if isinstance(projects, list) else projects
        ),
        "wrappers": (
            [w.get("id") for w in probe["wrappers"]]
            if isinstance(probe.get("wrappers"), list)
            else probe.get("wrappers")
        ),
        "terminal_commands": (
            [c.get("id") for c in probe["terminal_commands"]]
            if isinstance(probe.get("terminal_commands"), list)
            else probe.get("terminal_commands")
        ),
        "agent_commands": probe.get("agent_commands"),
        "config_version_on_disk": probe.get("config_version_on_disk"),
        "state_dir": probe.get("state_dir"),
        "db_exists": probe.get("db_exists"),
        "db_row_counts": probe.get("db_row_counts"),
        "db_projects": probe.get("db_projects"),
        "errors": probe.get("errors"),
    }


def step_verdict(name: str, probe: Optional[dict], server: Optional[dict]) -> Tuple[str, str]:
    if probe is None:
        return CANNOT, "no probe artifact was written for this step"
    if server is not None:
        status = server.get("status")
        if status == "unknown":
            return CANNOT, f"server start could not be evaluated: {server.get('detail', '')}"
        if status == "fail":
            return FAIL, f"server did not answer /health: {server.get('detail', '')}"
    if probe.get("auth_config_loadable") is False:
        errs = probe.get("errors") or []
        return FAIL, f"this version could not load config.json: {errs[:1]}"
    if probe.get("auth_config_loadable") is not True:
        return CANNOT, "config load was never attempted"
    projects = probe.get("projects")
    if not isinstance(projects, list):
        return CANNOT, "project list could not be read"
    if not projects:
        return FAIL, "config.json loaded but carries zero projects"
    return PASS, f"{len(projects)} projects readable by this version"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    run_dir = Path(args.run_dir).resolve()
    art = run_dir / "artifacts"

    steps = ordered_steps(run_dir)
    results = []
    prev_config = None
    prev_name = "(none)"

    for prefix, name in steps:
        cfg = load_json(art / f"{prefix}-{name}.config.json")
        probe = load_json(art / f"{prefix}-{name}.probe.json")
        server = load_json(art / f"{prefix}-{name}.server.json")
        verdict, reason = step_verdict(name, probe, server)
        expect_file = art / f"{prefix}-{name}.expect"
        expected = expect_file.read_text().strip() if expect_file.exists() else PASS
        if verdict == CANNOT:
            agreement = CANNOT
        elif verdict == expected:
            agreement = "AS-EXPECTED"
        else:
            agreement = "UNEXPECTED"
        results.append(
            {
                "step": f"{prefix} {name}",
                "verdict": verdict,
                "expected": expected,
                "agreement": agreement,
                "reason": reason,
                "config_diff_vs_prev": diff_configs(prev_config, cfg),
                "config_sha256": (probe or {}).get("config_sha256", CANNOT),
                "server": server or {"status": CANNOT},
                "seen": summarise_probe(probe),
            }
        )
        prev_config, prev_name = cfg, name

    meta = load_json(art / "meta-verdict.json")
    if meta is not None:
        expect_file = art / "meta.expect"
        expected = expect_file.read_text().strip() if expect_file.exists() else "INTACT"
        got = meta.get("verdict", CANNOT)
        if got == "CANNOT-DETERMINE":
            agreement = CANNOT
        elif got == expected:
            agreement = "AS-EXPECTED"
        else:
            agreement = "UNEXPECTED"
        results.append(
            {
                "step": "meta session-metadata-continuity",
                "verdict": got,
                "expected": expected,
                "agreement": agreement,
                "reason": meta.get("why", ""),
                "config_diff_vs_prev": {"added": [], "removed": [], "changed": []},
                "config_sha256": CANNOT,
                "server": {"status": "n/a", "detail": ""},
                "seen": {
                    "old_resolved": meta.get("old_resolved_after_downgrade"),
                    "new_resolved": meta.get("new_resolved_after_upgrade"),
                    "old_sees_session_id": meta.get("old_sees_session_id"),
                    "new_last_persisted": meta.get("new_last_persisted"),
                },
            }
        )
    else:
        results.append(
            {
                "step": "meta session-metadata-continuity",
                "verdict": CANNOT,
                "expected": "INTACT",
                "agreement": CANNOT,
                "reason": ("no meta-verdict.json - the metadata steps did not "
                           "run, which is not the same as metadata surviving"),
                "config_diff_vs_prev": {"added": [], "removed": [], "changed": []},
                "config_sha256": CANNOT,
                "server": {"status": CANNOT, "detail": ""},
                "seen": {},
            }
        )

    fails = [r for r in results if r["agreement"] == "UNEXPECTED"]
    unknowns = [r for r in results if r["agreement"] == CANNOT]
    overall = FAIL if fails else (CANNOT if unknowns else PASS)

    out = {"overall": overall, "steps": results}
    (run_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str) + "\n")

    print("=" * 74)
    print(f"ROUND TRIP VERDICT: {overall}")
    print("=" * 74)
    for r in results:
        print(f"\n[{r['verdict']:<17}] {r['step']}   (expected {r['expected']}: {r['agreement']})")
        print(f"    why:      {r['reason']}")
        print(f"    server:   {r['server'].get('status')} {r['server'].get('detail','')}")
        s = r["seen"]
        print(f"    projects: {s.get('project_count')}  wrappers: {s.get('wrappers')}")
        print(f"    termcmds: {s.get('terminal_commands')}")
        print(f"    cfg ver:  {s.get('config_version_on_disk')}   sha: {str(r['config_sha256'])[:12]}")
        print(f"    state:    {s.get('state_dir')}")
        print(f"    db:       exists={s.get('db_exists')} rows={s.get('db_row_counts')}")
        d = r["config_diff_vs_prev"]
        if "cannot_determine" in d:
            print(f"    cfg diff: {CANNOT}")
        else:
            print(f"    cfg diff: +{d['added']} -{d['removed']} ~{d['changed']}")
        if s.get("errors"):
            print(f"    errors:   {s['errors']}")
    print()
    return 1 if fails else (2 if unknowns else 0)


if __name__ == "__main__":
    sys.exit(main())
