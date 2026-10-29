
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Sequence

Card = Mapping[str, Any]


def _title(card: Card) -> str:
    return str(card.get("title") or f"card #{card['id']}")


def dealt(card: Card, chain_facts: Sequence[Mapping[str, str]] = (), note: str = "", **_: Any) -> str:
    known = "".join(f"fact {f['fact_id']}: {' '.join(str(f['title']).split())}\n" for f in list(chain_facts)[:3])
    return (f"You were dealt card #{card['id']}: {_title(card)}.\n{card.get('text') or ''}\n"
            f"Handoff so far: {card.get('handoff') or 'none yet'}.\n"
            + (f"The owner's note for you: {note}\n" if note else "")
            + (f"What your chain already knows:\n{known}" if known else "") +
            "Call swarm_card_start now (it answers the full card), keep the handoff current with swarm_card_handoff, and finish with swarm_card_finish (result, how-to-validate and needs_owner).")


def refresh(card: Card, **_: Any) -> str:
    return (f"Write your handoff into card #{card['id']} now with swarm_card_handoff: what is done, what is left, the next step. "
            "Then carry on.")


def pause_after_step(card: Card, **_: Any) -> str:
    return (f"Pause card #{card['id']} after your current step: finish the step, write your handoff into the card with "
            "swarm_card_handoff, then stop and wait. Do not start anything else.")


def pause_now(card: Card, **_: Any) -> str:
    return f"Stop now: the owner paused card #{card['id']}. Write your handoff into it with swarm_card_handoff, then wait."


def resume(card: Card, **_: Any) -> str:
    return f"Resume card #{card['id']}: read its handoff with swarm_card_get (or restart it with swarm_card_start, which answers the full card) and carry on from the next step."


def swap(card: Card, *, agent: str = "another agent", **_: Any) -> str:
    return (f"Card #{card['id']} moves to {agent}. Write your handoff into it with swarm_card_handoff now, "
            "then call swarm_card_release.")


def lapse_stop(card: Card, **_: Any) -> str:
    return f"Card #{card['id']} was handed off because it went quiet. Stop work on it and do not write to it again."


def owner_release(card: Card, **_: Any) -> str:
    return f"The owner took card #{card['id']} back. Stop work on it and do not write to it again."


def validation_failed(card: Card, *, proof: str = "", **_: Any) -> str:
    return (f"Validation failed on card #{card['id']}:\n{proof}\nFix it, update the handoff, and finish it again.")


def sent_back(card: Card, **_: Any) -> str:
    return (f"Card #{card['id']} ({_title(card)}) was sent back to you. The owner's note follows. Update the handoff with "
            "swarm_card_handoff, fix what it names, and call swarm_card_finish again (result, how-to-validate and needs_owner).")


def spawn_card_line(card: Card, chain_facts: Sequence[Mapping[str, str]] = ()) -> str:
    known = "".join(f"fact {f['fact_id']}: {' '.join(str(f['title']).split())}\n" for f in list(chain_facts)[:3])
    return (f"\n\nYour card is #{card['id']}: {_title(card)}. Call swarm_card_start before you begin (it answers the full card); the card is the whole job. "
            "Keep the handoff current with swarm_card_handoff, and finish with swarm_card_finish (result, how-to-validate and needs_owner)."
            + (f"\nWhat your chain already knows:\n{known}" if known else ""))


_TELLS: Dict[str, Callable[..., str]] = {
    "dealt": dealt, "refresh": refresh, "pause_after_step": pause_after_step, "pause_now": pause_now, "resume": resume, "swap": swap,
    "lapse_stop": lapse_stop, "owner_release": owner_release, "validation_failed": validation_failed, "sent_back": sent_back,
}


def tell_text(name: str, card: Card, **names: Any) -> Optional[str]:
    make = _TELLS.get(name)
    return None if make is None else make(card, **names)


def _who(names: Mapping[str, Any], key: str, fallback: str) -> str:
    return str(names.get(key) or fallback)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def post_text(name: str, card: Card, ctx: Mapping[str, Any]) -> Optional[str]:
    title, agent = _title(card), _who(ctx, "agent", "an agent")
    if name == "dealt":
        place = f" (#{ctx['place']})" if ctx.get("place") else ""
        return f"{_who(ctx, 'dealer', 'the owner')} dealt {title}{place} to {agent}"
    if name == "handed_off":
        old = _who(ctx, "old", "an agent")
        lead = f"{old} stopped responding; handed" if ctx.get("lapsed") else f"{old} handed"
        return f"{lead} {title} to {agent}, which starts from the handoff note"
    if name == "lapsed":
        return f"{agent} went quiet on {title} ({ctx.get('reason') or 'no sign of life'}); it is queued for the next deal"
    if name == "stalled":
        return f"{agent} stopped responding on {title}; dealing is off in {_who(ctx, 'project', 'this project')}, so it waits for you"
    if name == "paused":
        n = int(ctx.get("children") or 0)
        extra = f", also pauses {_plural(n, 'child card')}" + (f" and {', '.join(ctx['agent_names'])}" if ctx.get("agent_names") else "") if n else ""
        return f"paused {title}{extra}"
    if name == "resumed":
        return f"resumed {title}"
    if name in ("reorder_suggested", "reordered"):
        verb = "suggests moving" if name == "reorder_suggested" else "moved"
        where = f"above {ctx['other_title']}" if ctx.get("other_title") else "to the bottom"
        return f"{agent} {verb} {title} {where}: {ctx.get('reason') or 'no reason given'}"
    if name == "auto_done":
        return f"auto-done: {title}"
    if name == "waiting_for_slot":
        return f"{title} waits for a slot for {agent}"
    if name == "ready_to_validate":
        return f"{title} is ready to validate ({ctx.get('done', 0)} of {ctx.get('total', 0)} done)"
    if name == "validated":
        return f"validated {title} with {ctx.get('capability') or 'a validator'}"
    if name == "validation_failed":
        return f"validation failed on {title}"
    if name == "finished":
        return f"{agent} finished {title}"
    if name == "card_created":
        return f"{agent} made card {title}"
    if name == "learned":
        return f"learned from your send-back note on {title}: fact {ctx.get('fact_id', '')}"
    return None
