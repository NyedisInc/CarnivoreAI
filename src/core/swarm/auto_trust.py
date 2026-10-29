
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Optional

from src.core.approvals.extract import FAMILY_CLAUDE, KIND_TRUST, ROLE_OPTION

GATE_AWAITING = "awaiting_startup_prompt"

CARRIED_WAIT_SECONDS: float = 60.0

TRUST_LABELS = frozenset({"No, exit", "Yes, I trust this folder"})


def is_claude_trust_dialog(dialog: Any) -> bool:
    from src.core.notifications.sources.approvals import is_folder_trust_dialog

    if dialog is None or dialog.family != FAMILY_CLAUDE or dialog.kind != KIND_TRUST:
        return False
    if len(dialog.rows) != len(TRUST_LABELS) or {r.label.strip() for r in dialog.rows if r.role == ROLE_OPTION} != TRUST_LABELS:
        return False
    return is_folder_trust_dialog(dialog)


_PLAIN_HEAD = "Accessingworkspace:"
_PLAIN_TAIL = ("Quicksafetycheck:Isthisaprojectyoucreatedoroneyoutrust?(Likeyourowncode,awell-knownopensourceproject,orworkfromyourteam)."
               "Ifnot,takeamomenttoreviewwhat'sinthisfolderfirst.Claude" "Code'llbeabletoread,edit,andexecutefileshere."
               "SecurityguideNo,exitYes,Itrustthisfolder")


def plain_dialog_folder(dialog: Any) -> Optional[str]:
    if not is_claude_trust_dialog(dialog):
        return None
    kept = [re.sub(r"^[❯›>]\s*", "", ln.strip()) for ln in str(dialog.body).splitlines()]
    text = "".join(re.sub(r"\s+", "", ln) for ln in kept if ln and not set(ln) <= {"─", "-", "━"})
    if not text.startswith(_PLAIN_HEAD) or not text.endswith(_PLAIN_TAIL):
        return None
    shown = text[len(_PLAIN_HEAD):len(text) - len(_PLAIN_TAIL)]
    return shown if shown.startswith("/") and "…" not in shown else None


def shows_folder(dialog: Any, folder: str) -> bool:
    shown = plain_dialog_folder(dialog)
    return shown is not None and shown in {re.sub(r"\s+", "", folder), re.sub(r"\s+", "", os.path.realpath(folder))}


def made_by_carnivore(conn: sqlite3.Connection, folder: str) -> bool:
    target = os.path.realpath(folder)
    rows = conn.execute(
        "SELECT repo_dir AS path FROM swarm_agents WHERE rank = 'alpha' "
        "UNION SELECT p.root FROM companies c JOIN projects p ON p.id = c.hq_project_id "
        "UNION SELECT p.root FROM swarm_suggestions s JOIN projects p ON p.id = s.made_project_id").fetchall()
    from src.core.pack.trust_carry import store as carried

    return any(r[0] and os.path.realpath(str(r[0])) == str(r[0]) == target for r in rows) or carried.carried_op(conn, target) is not None


def may_auto_answer(conn: sqlite3.Connection, agent: dict, wake: Optional[dict], info: Any, dialog: Any, *, allow_unmeasured: bool = False) -> bool:
    from src.core.swarm.delivery import kickoff_recorded

    if wake is None or agent.get("torn_down_at") is not None or getattr(info, "agent_family", None) != "claude":
        return False
    if getattr(info, "startup_gate", None) == "ready" or not is_claude_trust_dialog(dialog):
        return False
    if kickoff_recorded(conn, agent["id"], f"wake:{wake['id']}"):
        return False
    work = getattr(info.session, "working_dir", None)
    repo = agent.get("repo_dir")
    if not work or not repo or os.path.realpath(str(repo)) != str(repo) or os.path.realpath(str(work)) != str(repo):
        return False
    from src.core.pack.trust_carry import store as carried

    if carried.carried_op(conn, str(work)) is not None:
        if not shows_folder(dialog, str(work)):
            return False
        if not allow_unmeasured and getattr(info, "startup_gate", None) != GATE_AWAITING:
            return False
    return made_by_carnivore(conn, str(work))


IMPORTS_LABELS = frozenset({"No, disable external imports", "Yes, allow external imports"})
_IMPORTS_HEAD = ("AllowexternalCLAUDE.mdfileimports?Thisproject'sCLAUDE.mdor.claude/rulesimportsfilesoutsidethecurrentworkingdirectory."
                 "Neverallowthisforthird-partyrepositories.Externalimports:")
_IMPORTS_TAIL = "Important:OnlyuseClaudeCodewithfilesyoutrust.Accessinguntrustedfilesmayposesecurityrisks"


def is_plain_imports_dialog(dialog: Any) -> bool:
    if dialog is None or dialog.family != FAMILY_CLAUDE or len(dialog.rows) != len(IMPORTS_LABELS):
        return False
    if {r.label.strip() for r in dialog.rows if r.role == ROLE_OPTION} != IMPORTS_LABELS:
        return False
    kept = [re.sub(r"^[❯›>]\s*", "", ln.strip()) for ln in str(dialog.body).splitlines()]
    text = "".join(re.sub(r"\s+", "", ln) for ln in kept if ln and not set(ln) <= {"─", "-", "━"})
    return text.startswith(_IMPORTS_HEAD) and _IMPORTS_TAIL in text
