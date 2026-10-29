
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, TypeVar

import structlog

from src.core import db
from src.core.db_reuse import datastore_pool
from src.core.swarm import alerts, alpha, answers, body, company_promote, delivery, facts, learning, project_agent, project_promote, promotion, push, reports, routing, seat_views, sleep_commit, store, suggest, switch, thread_port, turn_off, watch
from src.core.swarm.cards import dealer, port as card_port
from src.core.swarm.names import shown_name
from src.cplugs.sdk.cards import CardPort
from src.cplugs.sdk.swarm import AgentRef, SeatRef, SwarmError, ThreadPort, WakeTicket

logger = structlog.get_logger()

T = TypeVar("T")
Infos = Callable[[], Awaitable[List[Any]]]
_AGENT_PREFIX = "agent:"
_ACK_ONLY_PREFIXES = (delivery.STUCK_PREFIX, *alerts.ACK_PREFIXES, reports.REPORT_PREFIX, routing.WITHDRAWN_PREFIX)
WAKE_REASONS = frozenset({"owner_message", "crosstalk", "question", "learning", "spawn", "manual", "trust"})



class SwarmFacade:

    def __init__(self, state_dir: Path, infos: Infos, app_state: Any = None) -> None:
        self._state_dir = Path(state_dir)
        self._infos = infos
        self._app_state = app_state

    def _read(self, work: Callable[[sqlite3.Connection], T], default: T) -> T:
        path = db.db_path_for(self._state_dir)
        try:
            with closing(datastore_pool.lend(path)) as conn:
                return work(conn)
        except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
            datastore_pool.forget_if_broken(path, exc)
            logger.warning("swarm_facade_unreadable", error_type=type(exc).__name__, error=str(exc)[:300])
            return default

    def is_agent_key(self, list_key: str) -> bool:
        return bool(self._read(lambda conn: store.get_agent_by_thread_key(conn, list_key), None))

    def thread_changed(self, list_key: str) -> None:
        if self.is_agent_key(list_key):
            push.notify_roster()

    def agent_names(self, keys: Optional[Iterable[str]] = None) -> Dict[str, str]:
        wanted = None if keys is None else set(keys)

        def work(conn: sqlite3.Connection) -> Dict[str, str]:
            return {a["thread_key"]: shown_name(a) for a in store.list_agents(conn)
                    if a["thread_key"].startswith(_AGENT_PREFIX) and (wanted is None or a["thread_key"] in wanted)}

        return self._read(work, {})

    async def _ref(self, agent: Dict[str, Any]) -> AgentRef:
        row_id = agent["session_row_id"]
        session_id = None
        if row_id is not None:
            session_id = next((i.session.id for i in await self._infos()
                               if getattr(i, "session_row_id", None) == row_id), None)
        uuid = None
        if row_id is not None:
            def work(conn: sqlite3.Connection) -> Optional[str]:
                found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (row_id,)).fetchone()
                return found[0] if found and found[0] else None

            uuid = await asyncio.to_thread(self._read, work, None)
        return AgentRef(id=agent["id"], slug=agent["slug"], display_name=shown_name(agent), rank=agent["rank"],
                        thread_key=agent["thread_key"], state=agent["state"], session_id=session_id, session_uuid=uuid)

    async def agent_for_list(self, list_key: str) -> Optional[AgentRef]:
        agent = await asyncio.to_thread(self._read, lambda conn: store.get_agent_by_thread_key(conn, list_key), None)
        return await self._ref(agent) if agent else None

    async def bodies_among(self, infos: Iterable[Any]) -> frozenset:
        by_row = {getattr(i, "session_row_id", None): i.session.id for i in infos}
        by_row.pop(None, None)
        if not by_row:
            return frozenset()
        row_ids = sorted(by_row)

        def work(conn: sqlite3.Connection) -> List[int]:
            marks = ",".join("?" * len(row_ids))
            return [r[0] for r in conn.execute(f"SELECT session_row_id FROM swarm_agents WHERE session_row_id IN ({marks})", row_ids)]

        found = await asyncio.to_thread(self._read, work, [])
        return frozenset(by_row[r] for r in found)

    async def thread_for_session(self, session_id: str) -> Optional[str]:
        row_id = next((getattr(i, "session_row_id", None) for i in await self._infos() if i.session.id == session_id), None)
        if row_id is None:
            return None
        agent = await asyncio.to_thread(self._read, lambda conn: store.get_agent_by_session_row(conn, row_id), None)
        return agent["thread_key"] if agent else None

    def agent_seats(self) -> List[SeatRef]:
        return self._read(seat_views.agent_seats, [])

    def fallback_agent(self, project_key: str) -> Optional[SeatRef]:
        if not project_key.isdigit():
            return None
        return self._read(lambda conn: seat_views.fallback_seat(conn, int(project_key)), None)

    async def agent_by_id(self, agent_id: int) -> Optional[AgentRef]:
        def work(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            found = store.get_agent(conn, agent_id)
            return found if found and found["torn_down_at"] is None else None

        agent = await asyncio.to_thread(self._read, work, None)
        return await self._ref(agent) if agent else None

    async def agent_for_session_uuid(self, session_uuid: str) -> Optional[AgentRef]:
        def work(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            found = store.get_agent_by_session_uuid(conn, session_uuid)
            return found if found and found["torn_down_at"] is None else None

        agent = await asyncio.to_thread(self._read, work, None)
        return await self._ref(agent) if agent else None

    async def promote_session(self, session_uuid: str, project_key: str) -> AgentRef:
        if self._app_state is None:
            raise SwarmError("the Swarm body is not available in this context")
        if not project_key.isdigit():
            raise SwarmError("a project agent belongs to a project's list")
        if not switch.is_on():
            raise SwarmError(switch.OFF_MESSAGE)
        try:
            company_id = await company_promote.company_for_project(int(project_key))
            if company_id is not None:
                agent = await company_promote.promote_session(self._app_state, session_uuid, company_id)
            else:
                agent = await project_promote.promote_session(self._app_state, session_uuid, int(project_key))
        except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
            raise SwarmError("the Swarm datastore could not be read") from exc
        return await self._ref(agent)

    def company_hq(self, project_key: str) -> Optional[int]:
        if not project_key.isdigit():
            return None
        return self._read(lambda conn: company_promote.company_of_hq(conn, int(project_key)), None)

    async def retire_dead_project_agent(self, agent_id: int) -> bool:
        def work(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            dead = next((s for s in seat_views.agent_seats(conn) if s.agent_id == agent_id and s.rank == "project" and s.body_gone), None)
            return store.get_agent(conn, agent_id) if dead and store.tear_down(conn, agent_id) else None

        retired = await body.run_db(work)
        if retired is None:
            return False
        await turn_off.close_cards(retired["thread_key"])
        logger.info("swarm_dead_project_agent_retired", agent_id=agent_id)
        return True

    async def wake(self, agent_id: int, reason: str) -> WakeTicket:
        if self._app_state is None:
            raise SwarmError("the Swarm body is not available in this context")
        if reason not in WAKE_REASONS:
            raise SwarmError(f"unknown wake reason {reason!r}")
        result = await body.wake(self._app_state, agent_id, reason, "data")
        return WakeTicket(wake_id=result.wake_id, started=result.started)

    def is_waking(self, list_key: str) -> bool:
        return delivery.waking_for_thread(list_key)

    def record_delivery(self, agent_id: int, authority: str, source: str, source_ref: str, owner_text: Optional[str] = None) -> int:
        if authority not in ("owner", "data"):
            raise ValueError(f"authority must be owner or data, not {authority!r}")
        refs = {"owner_message_ref": source_ref} if authority == "owner" else {"source_ref": source_ref}
        with closing(db.connect(db.db_path_for(self._state_dir), create=False)) as conn:
            wake = store.get_open_wake(conn, agent_id)
            row = store.record_delivery(conn, agent_id, authority=authority, source=source,
                                        wake_id=wake["id"] if wake else None, **refs)
            agent = store.get_agent(conn, agent_id)
            if authority == "owner" and owner_text and agent is not None:
                learning.queue_skip_level(conn, agent, source_ref, owner_text)
            return row

    def discard_delivery(self, delivery_id: int, refusal: Any) -> None:
        if delivery.nothing_landed(refusal):
            delivery.discard(delivery_id)

    async def card_decided(self, swarm_ref: str, decision: str, note: str, owner_message_ref: str, *,
                           structured: Optional[Dict[str, Any]] = None) -> None:
        if self._app_state is None:
            raise SwarmError("the Swarm body is not available in this context")
        decided = await self._apply_decision(swarm_ref, decision, note, owner_message_ref, structured)
        port = thread_port.get()
        if port is not None:
            await port.settle_cards(swarm_ref, resolve=decided)

    async def _apply_decision(self, swarm_ref: str, decision: str, note: str, owner_message_ref: str,
                              structured: Optional[Dict[str, Any]] = None) -> bool:
        approve = decision == "approve"
        if not switch.is_on() and not swarm_ref.startswith(_ACK_ONLY_PREFIXES):
            raise SwarmError(switch.OFF_MESSAGE)
        if swarm_ref.startswith(delivery.TRUST_PREFIX):
            await delivery.answer_trust(self._app_state, swarm_ref, approve)
        elif swarm_ref.startswith((delivery.HELD_PREFIX, delivery.IMPORT_PREFIX, delivery.CHOICE_PREFIX)):
            await delivery.answer_dialog_card(self._app_state, swarm_ref, approve)
        elif swarm_ref.startswith(delivery.STUCK_PREFIX) or swarm_ref.startswith(alerts.ACK_PREFIXES):
            return True
        elif swarm_ref.startswith(sleep_commit.VISIBILITY_PREFIX):
            await sleep_commit.decide(self._app_state, swarm_ref, approve)
        elif swarm_ref.startswith((project_agent.GITINIT_PREFIX, project_agent.NAMING_PREFIX)):
            await project_agent.decide(self._app_state, swarm_ref, approve)
        elif swarm_ref.startswith(reports.REPORT_PREFIX):
            return True
        elif swarm_ref.startswith(facts.CONFLICT_PREFIX):
            await self._decide_conflict(swarm_ref[len(facts.CONFLICT_PREFIX):], approve)
        elif swarm_ref.startswith(routing.QUESTION_PREFIX):
            return await self._answer_question(swarm_ref[len(routing.QUESTION_PREFIX):], decision, note, owner_message_ref, structured)
        elif swarm_ref.startswith(routing.WITHDRAWN_PREFIX):
            return True
        elif swarm_ref.startswith(suggest.SUGGEST_PREFIX):
            await suggest.decide(self._app_state, swarm_ref, approve)
        elif swarm_ref.startswith(promotion.PROMOTION_PREFIX):
            try:
                await promotion.decide(self._app_state, swarm_ref, approve)
            except (promotion.PromotionRefused, body.BodyError) as exc:
                raise SwarmError(str(exc)) from None
        else:
            raise SwarmError(f"unknown Swarm card {swarm_ref.split(':', 1)[0]!r}")
        return True

    async def _decide_conflict(self, fact_id: str, accept_theirs: bool) -> None:
        try:
            await body.run_db(lambda c: facts.decide_conflict(c, fact_id, accept_theirs))
        except (facts.FactNotFound, facts.FactRefused) as exc:
            raise SwarmError(str(exc) or "that fact is gone") from None
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
            raise SwarmError("the decision could not be saved; try again") from exc

    async def _answer_question(self, raw_id: str, decision: str, note: str, owner_message_ref: str,
                               structured: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return await answers.owner_answer(self._app_state, int(raw_id), decision, note, owner_message_ref, structured=structured)
        except (ValueError, routing.QuestionRefused) as exc:
            raise SwarmError(str(exc) or "that question card is not valid") from None
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
            raise SwarmError("the answer could not be saved; try again") from exc

    def register_thread_port(self, port: Optional[ThreadPort]) -> None:
        thread_port.register(alerts.AlertingPort(port) if port is not None else None)
        if port is not None:
            alpha.schedule_ensure()
            if self._app_state is not None:
                watch.schedule_boot(self._app_state)

    def register_card_port(self, port: Optional[CardPort]) -> None:
        card_port.register(port)
        if port is None:
            dealer.unbind()
            return
        try:
            loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        dealer.bind(self._app_state, loop)

    def deal_requested(self, project_key: str) -> None:
        dealer.kick(project_key)
