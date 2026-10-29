
from __future__ import annotations

import asyncio
import dataclasses
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

import structlog

from src.cplugs.huddle import rules, service
from src.cplugs.huddle.cards import driven, flow, policy, queue, reads, tx
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

_FLOW_OPS: Dict[str, Callable[..., flow.FlowResult]] = {
    "start": lambda c, i, a, by, now: flow.start(c, i, agent_id=a["agent_id"], now=now),
    "handoff": lambda c, i, a, by, now: flow.handoff(c, i, agent_id=a["agent_id"], handoff=a.get("handoff"), progress=a.get("progress"), now=now),
    "release": lambda c, i, a, by, now: flow.release(c, i, by=by, reason=a.get("reason", ""), now=now),
    "deal": lambda c, i, a, by, now: queue.deal(c, i, agent_id=a["agent_id"], by=by, slot_ok=a.get("slot_ok", True), now=now,
                                                commit=by == "owner" or bool(a.get("commit")), reason=a.get("reason", "")),
    "move": lambda c, i, a, by, now: flow.move(c, i, before_id=a.get("before_id"), by=by, reason=a.get("reason", ""), now=now, pin_place=bool(a.get("pin_place"))),
    "suggest": lambda c, i, a, by, now: flow.suggest(c, i, before_id=a.get("before_id"), agent_id=a["agent_id"], reason=a.get("reason", ""), now=now),
    "pause": lambda c, i, a, by, now: flow.pause(c, i, mode=a["mode"], by=by, now=now),
    "resume": lambda c, i, a, by, now: flow.resume(c, i, by=by, now=now),
    "swap": lambda c, i, a, by, now: flow.swap(c, i, agent_id=a["agent_id"], by=by, now=now),
    "pin": lambda c, i, a, by, now: flow.pin(c, i, agent_id=a.get("agent_id"), place=bool(a.get("place")), by=by, now=now),
    "mark": lambda c, i, a, by, now: flow.mark(c, i, mark=a["mark"], by=by, detail=a.get("detail", ""), now=now),
    "lapse": lambda c, i, a, by, now: flow.lapse(c, i, reason=a.get("reason", ""), seen=a.get("seen"), now=now),
    "accept_child": lambda c, i, a, by, now: flow.accept_child(c, i, by_agent=a["by_agent"], report_id=a["report_id"], now=now),
    "complete_slot": lambda c, i, a, by, now: flow.complete_slot(c, i, now=now),
    "asked_refresh": lambda c, i, a, by, now: flow.asked_refresh(c, i, now=now),
    "set_lane": lambda c, i, a, by, now: flow.set_lane(c, i, queued=bool(a["queued"]), by=by, now=now),
    "archive": lambda c, i, a, by, now: flow.archive(c, i, on=bool(a["on"]), by=by, now=now, reason=a.get("reason", "")),
    "auto_promote": lambda c, i, a, by, now: flow.set_auto_promote(c, i, on=bool(a["on"]), by=by, now=now),
    "promote": lambda c, i, a, by, now: flow.promote(c, i, by=by, now=now),
    "queue": lambda c, i, a, by, now: queue.queue(c, i, by=by, reason=a.get("reason", ""), now=now),
    "owner_note": lambda c, i, a, by, now: flow.owner_note(c, i, note=a.get("note", ""), by=by, now=now),
    "validation": lambda c, i, a, by, now: flow.validation(c, i, state=a["state"], proof=a.get("proof", ""), agent_id=a.get("agent_id"), now=now,
                                                           capability=a.get("capability", ""), verdict=a.get("verdict", ""), replaces=a.get("replaces")),
}


class TaskManagerCardPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    async def _read(self, work: Callable[[Any], Any]) -> Any:
        store = service.store(self._ctx)

        def go() -> Any:
            with closing(store._read_connection()) as conn:
                return work(conn)

        return await asyncio.to_thread(go)

    async def card(self, card_id: int) -> Optional[Dict[str, Any]]:
        return await self._read(lambda conn: reads.one(conn, card_id))

    async def cards(self, *, list_keys: Sequence[str] = (), holder: Optional[int] = None, parent: Optional[int] = None,
                    columns: Sequence[str] = ()) -> List[Dict[str, Any]]:
        return await self._read(lambda conn: reads.many(conn, list_keys, holder=holder, parent=parent, columns=columns))

    async def policy_read(self, op: str, args: Mapping[str, Any]) -> Dict[str, Any]:
        return await self._read(lambda conn: reads.policy_read(conn, op, args))

    async def card_for_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        return await self._read(lambda conn: reads.card_for_report(conn, report_id))

    async def act(self, op: str, card_id: Optional[int], args: Mapping[str, Any], by: str) -> Dict[str, Any]:
        store = service.store(self._ctx)

        def work() -> Dict[str, Any]:
            try:
                if op in driven.OPS:
                    return driven.OPS[op](store, card_id, args, by)
                touched: Set[str] = set()
                now = time.time()
                with tx.write(store, touched) as conn:
                    if op == "create":
                        result = flow.create(conn, list_key=args["list_key"], title=args["title"], text=args.get("text", ""), by=by,
                                             origin=args["origin"], parent=args.get("parent"), how_to_validate=args.get("how_to_validate", ""),
                                             before_id=args.get("before_id"), now=now, summary=args.get("summary", ""), queued=bool(args.get("queued")))
                    elif op in _FLOW_OPS:
                        result = _FLOW_OPS[op](conn, card_id, args, by, now)
                    else:
                        raise ValueError(f"unknown card op {op!r}")
                    if result.data.get("changed", True) and result.card:
                        touched.add(result.card["list_key"])
                    touched.update(result.data.get("list_keys", ()))
                return {"card": result.card, "effects": [dataclasses.asdict(e) for e in result.effects], "data": result.data}
            except rules.TaskManagerStale as exc:
                raise CardRefused("stale", str(exc)) from exc
            except rules.TaskManagerNotFound as exc:
                raise CardRefused("not_a_card", str(exc)) from exc
            except rules.TaskManagerError as exc:
                raise CardRefused("refused", str(exc)) from exc

        return await asyncio.to_thread(work)

    async def policy(self, op: str, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
        store = service.store(self._ctx)

        def work() -> Dict[str, Any]:
            touched: Set[str] = set()
            now = time.time()
            try:
                with tx.write(store, touched) as conn:
                    if op == "set_rules":
                        touched.add(args["list_key"])
                        return {"card": None, "effects": [], "data": {"rules": policy.set_rules(conn, args["list_key"], args["changes"], by, now)}}
                    if op == "deal_state":
                        touched.add(args["project_key"])
                        changed = policy.deal_state(conn, args["project_key"], args["state"], now, offered=args.get("offered", ()),
                                                    attempt=bool(args.get("attempt")), only_from=args.get("only_from", ()))
                        return {"card": None, "effects": [], "data": {"changed": changed}}
                    if op == "set_grant":
                        touched.add("all")
                        return {"card": None, "effects": [], "data": {"grant": policy.set_grant(conn, args["scope"], args.get("slots"), by, args.get("reason", ""), now)}}
                    if op == "settle_suggestion":
                        state = {"apply": "applied", "dismiss": "dismissed"}[args["action"]]
                        row = policy.settle_suggestion(conn, args["suggestion_id"], state, now)
                        touched.add(row["list_key"])
                        result = None
                        if state == "applied":
                            result = flow.move(conn, row["card_id"], before_id=row["before_id"], by=by, reason=f"applied: {row['reason']}", now=now)
                        return {"card": result.card if result else None, "effects": [], "data": {"suggestion": row}}
                    raise ValueError(f"unknown card policy op {op!r}")
            except rules.TaskManagerError as exc:
                raise CardRefused("refused", str(exc)) from exc

        return await asyncio.to_thread(work)
