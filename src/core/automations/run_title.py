from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.core.automations import models as m
from src.core.timers.redact import redact

SUMMARY_CAP = 140
_REASONS = {
    m.R_MISSED: "the computer was asleep or the app was off at the scheduled time", m.R_DISABLED: "the automation was switched off",
    m.R_PAUSED: "the scheduler was paused", m.R_TWO_RUNNING: "two other automations were already running",
    m.R_PREV_RUNNING: "the previous run was still going", m.R_LOGIN: "the claude login needs attention",
    m.R_USAGE: "plan usage was over 90 percent", m.R_REFRESH: "a login token refresh was in progress",
    m.R_TARGET_MISSING: "the target no longer exists", m.R_INTERRUPTED: "the app stopped while it was running",
    m.R_TARGET_INVALID: "the target is no longer valid", "timeout": "it ran out of time", "turn_cap": "it hit its turn limit",
    "report_too_large": "the report was too large to keep", "cli_not_started": "the agent could not start"}
_TITLES = {m.SUCCEEDED: "{} finished", m.FAILED: "{} failed", m.SKIPPED: "{} was skipped", m.CANCELLED: "{} was canceled",
           m.WAITING: "{} needs you", m.RUNNING: "{} is running", m.CLAIMED: "{} is starting"}


def _clip(text: str) -> str:
    line = " ".join(redact(text).split())
    return line if len(line) <= SUMMARY_CAP else line[:SUMMARY_CAP - 3].rstrip() + "..."


def _reason_words(reason: Optional[str]) -> str:
    if not reason:
        return ""
    if reason.startswith("exit_") and reason[5:].isdigit():
        return f"the command exited with code {reason[5:]}"
    return _REASONS.get(reason, reason.replace("_", " "))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _detail(kind: Optional[str], report: Any) -> str:
    if not isinstance(report, dict):
        return ""
    if kind == "command" and isinstance(report.get("exit_code"), int):
        took = report.get("duration_s")
        return f"the command exited with code {report['exit_code']}" + (f" after {took} s" if isinstance(took, (int, float)) else "")
    if kind == "agent" and isinstance(report.get("final_text"), str) and report["final_text"].strip():
        return report["final_text"].strip().splitlines()[0]
    if kind == "swarm_card" and report.get("card_id"):
        return "dropped a card" + (f" in {report['column']}" if report.get("column") else "")
    if kind == "session_message" and isinstance(report.get("delivery"), dict):
        return "sent the message to the session"
    if kind == "sequence" and isinstance(report.get("steps"), list):
        steps = report["steps"]
        ok = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == m.SUCCEEDED)
        return f"{_count(len(steps), 'step')} ran, {ok} succeeded"
    lists = sum(len(v) for v in report.values() if isinstance(v, list))
    return f"report with {_count(lists, 'item')}" if lists else ""


def build(*, name: str, status: str, kind: Optional[str] = None, reason: Optional[str] = None, report: Any = None,
          output_empty: Optional[bool] = None) -> Tuple[str, str]:
    label = (name or "").strip() or "this automation"
    title = _TITLES.get(status, "{} ended").format(label)
    why = _reason_words(reason)
    if status == m.SUCCEEDED:
        if output_empty:
            title, summary = f"{label} found nothing", "finished with nothing to report"
        else:
            summary = _detail(kind, report) or ("finished and left a report" if report else "finished")
    elif status == m.FAILED:
        summary = why or "it failed"
    elif status == m.SKIPPED:
        summary = f"skipped because {why}" if why else "skipped"
    elif status == m.WAITING:
        summary = "waiting for you to continue it"
    elif status == m.CANCELLED:
        summary = "canceled before it finished"
    else:
        summary = "not finished yet"
    return title, _clip(summary)
