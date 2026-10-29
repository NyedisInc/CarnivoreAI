
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

import structlog

from src.core.approvals import carried_trust
from src.core.approvals.auto_answer import catalog, projects, rules
from src.core.approvals.auto_answer.press import Answer, AckRefused, route_answer
from src.core.swarm.auto_trust import CARRIED_WAIT_SECONDS

logger = structlog.get_logger()

MAX_ATTEMPTS: int = 3

Info = Callable[[Any], Any]


def _read_process_rows() -> Optional[List[Any]]:
    from src.core.claude_resume_argv import list_process_table

    return list_process_table()


def grid_policy() -> catalog.Policy:
    from src.core.approvals import beast_policy

    return beast_policy.current()


def rule_on(policy: catalog.Policy, rule_id: str) -> bool:
    return policy.rule_on(rule_id) is True


def trust_scope(policy: catalog.Policy) -> str:
    return policy.trust_scope()


def answers_own_dev_channels(dialog: Any) -> bool:
    from src.core.approvals.dev_channels import carnivore_answers

    return rule_on(grid_policy(), catalog.RULE_DEV_CHANNELS) and carnivore_answers(dialog)


class AutoAnswerEngine:

    def __init__(self, app_state: Any, get_manager: Callable[[], Any], *, policy: Optional[Callable[[], catalog.Policy]] = None,
                 answer: Optional[Answer] = None, info: Optional[Info] = None, seams: Optional[rules.Seams] = None,
                 on_pressed: Optional[Callable[..., None]] = None, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or time.monotonic
        self._enabled = answer is not None or app_state is not None
        self._policy = policy or grid_policy
        self._answer: Answer = answer or route_answer(app_state, get_manager)
        self._info: Info = info or self._manager_info(get_manager)
        self._seams = seams or rules.Seams(_read_process_rows, carried_trust.carried_op_for, carried_trust.carried_imports_for, projects.in_projects_db)
        self._on_pressed = on_pressed
        self._state: Dict[tuple, list] = {}
        self._inflight: Set[tuple] = set()
        self._tasks: Set[asyncio.Task] = set()

    @staticmethod
    def _manager_info(get_manager: Callable[[], Any]) -> Info:
        async def read(session_id: str) -> Any:
            manager = get_manager()
            return await manager.get_session_info(session_id) if manager is not None else None
        return read

    def on_observation(self, target: Any, observation: Any) -> Optional[asyncio.Task]:
        session_id = str(getattr(target, "session_id", "") or "")
        evidence = getattr(observation, "evidence", None)
        dialog = getattr(evidence, "dialog", None)
        if not self._enabled or not session_id or dialog is None or getattr(observation, "stale", False):
            return None
        if session_id.startswith(("adopted:", "remote:")):
            return None
        rule = rules.rule_for(dialog)
        if rule is None:
            return None
        policy = self._policy()
        if not rule_on(policy, rule.info.id):
            return None
        key = (session_id, rule.info.id)
        identity = tuple(getattr(evidence, "identity", None) or ())
        instance = identity[:4] if len(identity) >= 4 else None
        if instance is None or key in self._inflight or (rule.needs_pid and instance[3] is None):
            return None
        entry = self._state.get(key)
        if entry is not None and not any(old is not None and new is not None and old != new for old, new in zip(entry[0], instance)):
            entry[0] = tuple(new if new is not None else old for old, new in zip(entry[0], instance))
        else:
            entry = self._state[key] = [instance, 0, False, self._clock()]
        if rule.needs_gate and not entry[2] and self._clock() - entry[3] > CARRIED_WAIT_SECONDS:
            entry[2] = True
        if entry[2] or entry[1] >= MAX_ATTEMPTS:
            return None
        scope = trust_scope(policy)
        self._inflight.add(key)
        ctx = rules.Ctx(session_id, dialog, instance[3], scope, self._info, self._seams)
        task = asyncio.get_running_loop().create_task(self._run(key, entry, rule, ctx))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, key: tuple, entry: list, rule: rules.ScreenRule, ctx: rules.Ctx) -> None:
        session_id, rule_id = key
        try:
            verdict = await rule.guard(ctx)
            if verdict.outcome == rules.WAIT:
                return
            if verdict.outcome == rules.RETRY:
                entry[1] += 1
                logger.info("auto_answer_skipped", session_id=session_id, rule=rule_id, reason=verdict.reason)
                return
            if verdict.outcome != rules.ALLOW:
                entry[2] = True
                logger.info("auto_answer_skipped", session_id=session_id, rule=rule_id, reason=verdict.reason)
                return
            entry[1] += 1
            try:
                await self._answer(session_id, ctx.dialog.fingerprint, rule.label)
            except AckRefused as exc:
                logger.info("auto_answer_refused", session_id=session_id, rule=rule_id, reason=exc.reason, attempt=entry[1])
                return
            entry[2] = True
            logger.info("auto_answer_pressed", session_id=session_id, rule=rule_id, risk=rule.info.risk, label=rule.label,
                        evidence=verdict.evidence, fingerprint=ctx.dialog.fingerprint[:12])
            await self._announce(session_id, ctx, rule, verdict.evidence)
        finally:
            self._inflight.discard(key)

    async def _announce(self, session_id: str, ctx: rules.Ctx, rule: rules.ScreenRule, evidence: str) -> None:
        if self._on_pressed is None:
            return
        info = await self._info(session_id)
        if info is None:
            logger.info("auto_answer_unrecorded", session_id=session_id, rule=rule.info.id, reason="row_gone")
            return
        self._on_pressed(info, ctx.dialog, rule.info.id, rule.label, evidence)

    def forget(self, live_ids: Iterable[str]) -> None:
        if not self._state:
            return
        live = set(live_ids)
        for key in [k for k in self._state if k[0] not in live]:
            del self._state[key]
