
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Iterable, Optional

from src.core.approvals.auto_answer import catalog
from src.core.approvals.auto_answer.engine import AutoAnswerEngine
from src.core.approvals.auto_answer.rules import Seams


class FixedPolicy:

    def __init__(self, scope: str = catalog.DEFAULT_SCOPE, off: Iterable[str] = ()) -> None:
        self.scope = scope
        self.off = set(off)

    def rule_on(self, rule_id: str) -> bool:
        return rule_id not in self.off

    def trust_scope(self) -> str:
        return self.scope


def make_engine(*, answer: Callable[..., Any], info: Optional[Callable[[str], Any]] = None, rows: Optional[Callable[[], Any]] = None,
                lookup: Optional[Callable[[str], Optional[str]]] = None, lookup_imports: Optional[Callable[[str], bool]] = None,
                in_projects: Optional[Callable[[str], bool]] = None, policy: Optional[Any] = None, clock: Optional[Callable[[], float]] = None,
                on_pressed: Optional[Callable[..., None]] = None) -> AutoAnswerEngine:
    async def no_info(_sid: str) -> Any:
        return SimpleNamespace(session=SimpleNamespace(id=_sid, working_dir=None), agent_family="claude", startup_gate=None, tmux_session="t")

    seams = Seams(rows or (lambda: None), lookup or (lambda _f: None), lookup_imports or (lambda _f: False), in_projects or (lambda _f: False))
    chosen = policy or FixedPolicy()
    return AutoAnswerEngine(None, lambda: None, policy=lambda: chosen, answer=answer, info=info or no_info,
                            seams=seams, on_pressed=on_pressed, clock=clock)
