
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from src.cplugs.sdk import ports

NAME = "huddle.artifacts"


class ArtifactSource(Protocol):

    async def posted(self) -> List[Dict[str, Any]]:
        pass

    async def page(self, item_id: int, file_id: str) -> Optional[str]:
        pass


def get() -> Optional[ArtifactSource]:
    return ports.get(NAME)
