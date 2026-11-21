
from __future__ import annotations

from typing import Annotated, Any, ClassVar, FrozenSet

from pydantic import BaseModel, ConfigDict, StringConstraints, model_serializer

ItemId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class SidecarModel(BaseModel):
    """Base of every sidecar object: unknown keys refused, and the ``SPARSE`` fields left out of the file while empty."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    SPARSE: ClassVar[FrozenSet[str]] = frozenset()
    KEEP_EMPTY: ClassVar[FrozenSet[str]] = frozenset()

    @model_serializer(mode="wrap")
    def _drop_sparse(self, handler: Any) -> Any:
        data = handler(self)
        for name in self.SPARSE:
            value = data.get(name)
            if value is None or (value == {} and name not in self.KEEP_EMPTY):
                data.pop(name, None)
        return data
