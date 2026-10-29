"""What a woken agent is told first (docs/swarm.md 4.2 step 8): the desk file for a fresh wake, a line for a resume.

A fresh wake starts a new conversation, so everything dynamic rides in ``desk.md`` and the paste is one pointer
sentence. A resume replays the old conversation, so its wake message IS the delivery. Both carry the reporting duty;
the learning inbox rides both (:mod:`learning`); the secret scan runs on the whole file before it is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.swarm import conflicts, definition, desk as desk_mod, launch, learning, memory
from src.core.swarm import settings as swarm_settings

_REASONS = {
    "owner_message": "the owner wrote to you in your thread",
    "crosstalk": "another agent sent you a message",
    "question": "a question was routed to you",
    "learning": "there is something new in your learning inbox",
    "spawn": "you were just created to do a job",
    "manual": "the owner woke you by hand",
    "trust": "the folder trust question was answered",
}


REPORTING_DUTY = ("Reporting duty: when your job is done, call swarm_report with a summary for your parent (an agent with no "
                  "parent tells the owner on its thread). Answer an agent that wrote to you with crosstalk_reply; a huddle "
                  "note does not count as an answer, and only the owner's words reset the crosstalk loop breaker.")

CARD_DUTY = ("Card duty: if you hold a card, keep its handoff current with swarm_card_handoff, write it before you stop, and "
             "finish the card with swarm_card_finish (result plus how-to-validate, and remember for what you learned) when the work is done; Done is the owner's "
             "call, never yours. Asking: swarm_ask takes a one-sentence summary the owner can answer without reading code "
             "(no file names, line numbers or code; say what the choice changes for the owner), with every detail in question.")


CONFLICT_DUTY = ("Capacity: there is no fixed agent limit. A spawn of a new agent the computer cannot take is refused with \"system is "
                 "pegged, try later\" and a retry_after: wait that long, then try again. When a git pull --rebase or merge stops "
                 f"on a conflict, a push is rejected, or you wait on the merge lock, call swarm_conflict with that kind. "
                 f"{conflicts.THRESHOLD} reports in {conflicts.WINDOW_S // 60} minutes cap your project at "
                 f"{conflicts.THROTTLED_WORKERS} live agents until {conflicts.WINDOW_S // 60} minutes pass with none.")


def naming_line(agent: Dict[str, Any], family_on: bool) -> str:
    if not family_on or agent.get("naming_state") != "approved" or not agent.get("naming_family") or not agent.get("persona"):
        return ""
    return (f"The owner approved your naming family: {agent['naming_family']}. Your persona is {agent['persona']} "
            f"(shown as {agent['display_name']}). Give every child you spawn a persona name from that family "
            "(swarm_spawn name), within the naming rules.")


def desk_file(state_dir: Path, agent_id: int) -> Path:
    return launch.desk_dir(state_dir, agent_id) / "desk.md"


def render_desk(agent: Dict[str, Any], reason: str, orders: str, work: desk_mod.Desk, family_on: bool = False) -> str:
    lines = [f"# desk: {agent['display_name']}", "", f"job: {agent['job']}"]
    if agent.get("goal"):
        lines += ["", "goal:", str(agent["goal"])]
    lines += ["", "## why you are awake", _REASONS.get(reason, "you were woken")]
    if orders.strip():
        lines += ["", "orders:", orders.strip()]
    named = naming_line(agent, family_on)
    if named:
        lines += ["", "## your name", named]
    server, data = desk_mod.render_parts(work)
    lines += ["", "## open work"] + server
    rules = definition.rank_rules(agent["rank"])
    lines += ["", REPORTING_DUTY, "", CARD_DUTY, "", CONFLICT_DUTY] + (["", rules] if rules else []) + desk_mod.data_block(data)
    return "\n".join(lines) + "\n"


def write_desk(state_dir: Path, agent: Dict[str, Any], reason: str, orders: str, work: desk_mod.Desk) -> Path:
    path = desk_file(state_dir, agent["id"])
    text = render_desk(agent, reason, orders, work, swarm_settings.naming_family_on())
    memory.refuse_secrets(text, f"desk/{agent['id']}/desk.md")
    memory.atomic_write(path, text)
    return path


def fresh_message(path: Path) -> str:
    return f"Read {path} first."


def resume_message(reason: str, orders: str, agent: Optional[Dict[str, Any]] = None,
                   inbox: Optional[List[Dict[str, Any]]] = None, family_on: bool = False) -> str:
    why = _REASONS.get(reason, "you were woken")
    named = naming_line(agent, family_on) if agent else ""
    inbox_lines = learning.render(inbox or [])
    rules = definition.rank_rules(agent["rank"]) if agent else ""
    return (f"You are awake again: {why}." + (f"\n\n{orders.strip()}" if orders.strip() else "")
            + (f"\n\n{named}" if named else "") + f"\n\n{REPORTING_DUTY}\n\n{CARD_DUTY}\n\n{CONFLICT_DUTY}" + (f"\n\n{rules}" if rules else "")
            + ("\n" + "\n".join(desk_mod.data_block(inbox_lines)) if inbox_lines else ""))
