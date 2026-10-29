
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, runtime_checkable

from src.cplugs.sdk.swarm import SwarmError


class CardRefused(SwarmError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class CardPort(Protocol):

    async def card(self, card_id: int) -> Optional[Dict[str, Any]]:
        pass

    async def cards(self, *, list_keys: Sequence[str] = (), holder: Optional[int] = None, parent: Optional[int] = None,
                    columns: Sequence[str] = ()) -> List[Dict[str, Any]]:
        pass

    async def policy_read(self, op: str, args: Mapping[str, Any]) -> Dict[str, Any]:
        pass

    async def card_for_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        pass

    async def act(self, op: str, card_id: Optional[int], args: Mapping[str, Any], by: str) -> Dict[str, Any]:
        pass

    async def policy(self, op: str, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
        pass
