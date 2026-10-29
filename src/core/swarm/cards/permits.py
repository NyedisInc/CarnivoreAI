
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping, Optional

HOLDER_OPS: FrozenSet[str] = frozenset({"start", "handoff", "finish", "release"})
DEALER_OPS: FrozenSet[str] = frozenset({"deal", "reorder", "swap", "auto_promote"})
PROJECT_OPS: FrozenSet[str] = frozenset({"queue"})
CLOSER_OPS: FrozenSet[str] = frozenset({"close"})
CURATOR_OPS: FrozenSet[str] = frozenset({"agent_archive", "agent_delete"})
OWNER_ONLY: FrozenSet[str] = frozenset({"done", "send_back", "pause", "resume", "pin", "move", "settle_suggestion", "set_rules",
                                        "set_column", "archive", "delete"})


def _is_dealer(agent: Mapping[str, Any], card: Mapping[str, Any], company_id: Optional[int]) -> bool:
    rank = agent.get("rank")
    if rank == "alpha":
        return True
    if rank == "project":
        return str(agent.get("thread_key")) == str(card["list_key"])
    return rank == "company" and company_id is not None and agent.get("company_id") == company_id


def check(agent: Optional[Dict[str, Any]], op: str, card: Optional[Mapping[str, Any]], args: Mapping[str, Any], *,
          company_id: Optional[int] = None) -> Optional[str]:
    if agent is None:
        return None
    if op in OWNER_ONLY:
        return "only the owner does that"
    if card is None:
        return None
    holder = (card.get("holder") or {}).get("agent_id")
    if op in HOLDER_OPS:
        if holder == agent["id"] or (op == "start" and card.get("dealt_to") == agent["id"]):
            return None
        return "you do not hold this card"
    if op in PROJECT_OPS:
        if agent.get("rank") == "project" and str(agent.get("thread_key")) == str(card["list_key"]):
            return None
        return "only the project agent of this card's own project queues it"
    if op in CLOSER_OPS:
        if _is_dealer(agent, card, company_id):
            return None
        return "only the project agent of this card's project, its company agent or Alpha closes it"
    if op in CURATOR_OPS:
        if _is_dealer(agent, card, company_id):
            return None
        return "only the project agent of this card's project, its company agent or Alpha archives or deletes it"
    if op in DEALER_OPS:
        if _is_dealer(agent, card, company_id):
            return None
        return "only the project agent of this list, its company agent or Alpha deals cards here"
    return f"unknown card op {op}"


def can_create(agent: Dict[str, Any], list_key: str, parent: Optional[Mapping[str, Any]], *, company_id: Optional[int] = None,
               parent_company_id: Optional[int] = None) -> Optional[str]:
    rank = agent.get("rank")
    if rank in ("task", "feature"):
        if parent is None or (parent.get("holder") or {}).get("agent_id") != agent["id"]:
            return "a task or feature agent makes only child cards of the card it holds"
        return None if str(parent["list_key"]) == str(list_key) else "a child card goes in its parent's list"
    if rank == "project" and parent is not None and str(parent["list_key"]) != str(agent.get("thread_key")):
        return "a project agent adds children only under cards in its own queue"
    if parent is not None and rank in ("company", "alpha") and not str(list_key).isdigit():
        return "name the project (project_id) the child card goes in"
    if rank == "company" and parent is not None and not _company_parent(agent, parent, parent_company_id):
        return "a company agent adds children only under its own cards or its company's project cards"
    if _is_dealer(agent, {"list_key": list_key}, company_id) or (rank == "company" and str(agent.get("thread_key")) == str(list_key)):
        return None
    return "you may not make cards in that list"


def _company_parent(agent: Mapping[str, Any], parent: Mapping[str, Any], parent_company_id: Optional[int]) -> bool:
    if str(parent["list_key"]) == str(agent.get("thread_key")):
        return True
    return str(parent["list_key"]).isdigit() and parent_company_id is not None and parent_company_id == agent.get("company_id")
