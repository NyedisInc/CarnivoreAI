from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.automations.scrooge.ai_pass import AiOutcome

SCHEMA = "scrooge/1"
OPUS_SHARE_PCT, OPUS_MIN_COST_SHARE_PCT = 70.0, 10.0
SUBAGENT_SHARE_PCT = 50.0
THINKING_SHARE_PCT = 60.0
COMPACTIONS_MIN = 20
RULE_TOKENS_MIN = 5000
OVERLAP_PCT, OVERLAP_MIN_LINES = 30.0, 5

_FIX = {
    "L1": "Look at which tasks in this project run on the most expensive model but are routine (searching, formatting, "
          "simple edits). Suggest where a cheaper model tier fits and what setting or habit would make it the default. "
          "Propose the change as a diff and wait for my yes before editing anything.",
    "L2": "Look at how sub-agents are used in this project and where they run without a bound. Propose limits (scope, "
          "turn counts, budgets) as a diff and wait for my yes before editing anything.",
    "L3": "Read the rule files in this project (CLAUDE.md, AGENTS.md and friends). Find text that is repeated between them or "
          "with my global rules, or that is too long to earn its tokens. Propose trims as a diff and wait for my yes before editing.",
    "L5": "This project compacts or resumes very large contexts often. Suggest how to split the work into fresh, smaller "
          "sessions, and what notes to keep in files instead. Wait for my yes before editing anything.",
    "L6": "Thinking tokens are a large share of the output here. Suggest where a lower effort setting would do and how to "
          "set it for this project. Propose the change and wait for my yes before editing anything.",
}


def finding_id(project_id: Optional[int], lever: str, title: str) -> str:
    return hashlib.sha256(f"{project_id}|{lever}|{title}".encode("utf-8")).hexdigest()[:16]


def _finding(project: Optional[Dict[str, Any]], lever: str, severity: str, title: str, evidence: str,
             source: str = "numbers", saving: Optional[float] = None) -> Dict[str, Any]:
    pid = project["project_id"] if project else None
    fix = None if project is None or project.get("home_folder") else _FIX.get(lever)
    return {"finding_id": finding_id(pid, lever, title), "project_id": pid, "lever": lever, "severity": severity,
            "title": title, "evidence": evidence, "est_saving_usd_month": saving, "fix_prompt": fix, "source": source}


def numbers_findings(projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in projects:
        name, share = p["name"], p.get("share_pct") or 0.0
        top = max(p["model_mix"], key=lambda item: item["share_pct"], default=None)
        if top and "opus" in top["model"].lower() and top["share_pct"] >= OPUS_SHARE_PCT and share >= OPUS_MIN_COST_SHARE_PCT:
            out.append(_finding(p, "L1", "high" if share >= 30 else "medium", f"{name}: mostly the top model",
                                f"{top['share_pct']}% of this project's root-folder spend is {top['model']}; the project is {share}% of total spend."))
        if (p.get("subagent_share_pct") or 0) >= SUBAGENT_SHARE_PCT:
            out.append(_finding(p, "L2", "medium", f"{name}: sub-agents are most of the spend",
                                f"sub-agents are {p['subagent_share_pct']}% of this project's estimated cost."))
        if (p.get("compactions") or 0) >= COMPACTIONS_MIN:
            out.append(_finding(p, "L5", "low", f"{name}: many compactions",
                                f"{int(p['compactions'])} compactions in the window (a proxy for resumed, very large contexts)."))
        if (p.get("thinking_share_pct") or 0) >= THINKING_SHARE_PCT:
            out.append(_finding(p, "L6", "medium", f"{name}: thinking is most of the output",
                                f"thinking tokens are {p['thinking_share_pct']}% of output tokens."))
        for rule in p["rule_files"]:
            if rule["oversize"] or rule["est_tokens"] >= RULE_TOKENS_MIN:
                out.append(_finding(p, "L3", "medium", f"{name}: {rule['path']} is large",
                                    f"{rule['path']} is {rule['bytes']} bytes (about {rule['est_tokens']} tokens, an estimate)."))
        for pair in p["overlap"]:
            if pair["shared_pct"] >= OVERLAP_PCT and pair["shared_lines"] >= OVERLAP_MIN_LINES:
                out.append(_finding(p, "L3", "medium", f"{name}: {pair['a']} repeats {pair['b']}",
                                    f"{pair['shared_lines']} lines ({pair['shared_pct']}%) of {pair['a']} are also in {pair['b']}."))
    return out


def merge_findings(numbers_side: List[Dict[str, Any]], ai: AiOutcome, projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {p["project_id"]: p for p in projects}
    merged = {f["finding_id"]: f for f in numbers_side}
    for f in ai.findings:
        project = by_id.get(f["project_id"])
        row = _finding(project, f["lever"], f["severity"], f["title"], f["evidence"], "ai", f["est_saving_usd_month"])
        row["fix_prompt"] = None if project is None or project.get("home_folder") else f["fix_prompt"]
        merged.setdefault(row["finding_id"], row)
    return list(merged.values())


def build_report(numbers: Dict[str, Any], rules_by_project: Dict[int, Dict[str, list]], ai: AiOutcome,
                 now: datetime) -> Dict[str, Any]:
    totals = numbers["totals"]
    projects = [{"project_id": p["project_id"], "name": p["name"], "folder": p["folder"], "home_folder": p["home_folder"],
                 "est_cost_usd": p["est_cost_usd"], "share_pct": p["share_pct"], "model_mix": p["model_mix"],
                 "root_folder_only": p["root_folder_only"], "subagent_share_pct": p["subagent_share_pct"],
                 "thinking_share_pct": p["thinking_share_pct"], "cache_write_1h_share_pct": p["cache_write_1h_share_pct"],
                 "compactions": p["compactions"], "cache_write_1h": p["cache_write_1h"],
                 **rules_by_project.get(p["project_id"], {"rule_files": [], "overlap": []})} for p in numbers["projects"]]
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "window": numbers["window"], "scope": numbers["scope"],
            "totals": {"est_cost_usd": totals["est_cost_usd"], "compactions": totals["compactions"],
                       "tokens": {k: totals[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h", "thinking")}},
            "projects": projects, "levers": numbers["levers"],
            "findings": merge_findings(numbers_findings(projects), ai, projects),
            "ai": {"status": ai.status, "model": ai.model, "cost_usd": ai.cost_usd, "error": ai.error}}
