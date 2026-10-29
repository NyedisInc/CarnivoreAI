
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Iterable, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.cplugs.sdk.cards import CardPort


class SwarmError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRef:

    id: int
    slug: str
    display_name: str
    rank: str
    thread_key: str
    state: str
    session_id: Optional[str] = None
    session_uuid: Optional[str] = None


@dataclass(frozen=True)
class SeatRef:

    agent_id: int
    rank: str
    project_key: Optional[str]
    session_uuid: Optional[str]
    body_gone: bool = False
    display_name: str = ""


@dataclass(frozen=True)
class WakeTicket:

    wake_id: int
    started: bool


Messenger = Callable[[str, str], Awaitable[Any]]


@runtime_checkable
class ThreadPort(Protocol):

    async def ensure_thread(self, thread_key: str, title: str) -> None:
        pass

    async def post_card(self, thread_key: str, kind: str, title: str, text: str, swarm_ref: str) -> int:
        pass

    async def check_form(self, questions: Any) -> str:
        pass

    async def stage_form(self, question_id: int, questions: Any) -> None:
        pass

    async def post_owner_message(self, thread_key: str, text: str) -> str:
        pass

    async def owner_message(self, thread_key: str, ref: str) -> Optional[str]:
        pass

    async def post_agent_message(self, thread_key: str, text: str, author_key: str) -> str:
        pass

    async def post_traffic(self, thread_key: str, text: str, swarm_ref: str) -> str:
        pass

    async def mark_phone_sent(self, item_id: int) -> None:
        pass

    async def close_card(self, item_id: int, state: str) -> None:
        pass

    async def settle_cards(self, swarm_ref: str, *, prefix: bool = False, resolve: bool = False) -> None:
        pass

    async def close_open_cards(self, thread_key: str, prefix: str) -> None:
        pass

    async def open_card_id(self, thread_key: str, swarm_ref: str) -> Optional[int]:
        pass

    async def open_cards(self) -> List[Dict[str, Any]]:
        pass

    async def archive_thread(self, thread_key: str) -> None:
        pass

    async def read_thread(self, thread_key: str, limit: int, *, cards: bool = True) -> List[Dict[str, Any]]:
        pass

    async def tell(self, thread_key: str, session_id: str, text: str, *, message: Messenger) -> Any:
        pass


@runtime_checkable
class SwarmCapability(Protocol):

    def is_agent_key(self, list_key: str) -> bool:
        pass

    async def agent_for_list(self, list_key: str) -> Optional[AgentRef]:
        pass

    def agent_names(self, keys: Optional[Iterable[str]] = None) -> Dict[str, str]:
        pass

    async def thread_for_session(self, session_id: str) -> Optional[str]:
        pass

    async def bodies_among(self, infos: Iterable[Any]) -> frozenset:
        pass

    def agent_seats(self) -> List[SeatRef]:
        pass

    def fallback_agent(self, project_key: str) -> Optional[SeatRef]:
        pass

    async def agent_by_id(self, agent_id: int) -> Optional[AgentRef]:
        pass

    async def agent_for_session_uuid(self, session_uuid: str) -> Optional[AgentRef]:
        pass

    async def promote_session(self, session_uuid: str, project_key: str) -> AgentRef:
        pass

    def company_hq(self, project_key: str) -> Optional[int]:
        pass

    async def retire_dead_project_agent(self, agent_id: int) -> bool:
        pass

    async def wake(self, agent_id: int, reason: str) -> WakeTicket:
        pass

    def is_waking(self, list_key: str) -> bool:
        pass

    def record_delivery(self, agent_id: int, authority: str, source: str, source_ref: str, owner_text: Optional[str] = None) -> int:
        pass

    def discard_delivery(self, delivery_id: int, refusal: Any) -> None:
        pass

    async def card_decided(self, swarm_ref: str, decision: str, note: str, owner_message_ref: str, *,
                           structured: Optional[Dict[str, Any]] = None) -> None:
        pass

    def thread_changed(self, list_key: str) -> None:
        pass

    def register_thread_port(self, port: Optional[ThreadPort]) -> None:
        pass

    def register_card_port(self, port: Optional["CardPort"]) -> None:
        pass

    def deal_requested(self, project_key: str) -> None:
        pass
