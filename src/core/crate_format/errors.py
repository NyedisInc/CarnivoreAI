
from __future__ import annotations

from typing import List, Optional, Sequence


class CrateError(Exception):

    code: str = "malformed"


class CrateMalformed(CrateError):

    code = "malformed"

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems: List[str] = list(problems)
        super().__init__("; ".join(self.problems) or "malformed crate")


class UnsafeName(CrateMalformed):

    def __init__(self, problem: str) -> None:
        super().__init__([problem])


class CrateTooNew(CrateError):

    code = "too_new"

    def __init__(self, major: int) -> None:
        self.major = major
        super().__init__(f"this crate was written by a newer Carnivore (format {major}.x); update to read it")


class CrateCorrupt(CrateError):

    def __init__(self, problems: Sequence[str], code: str = "blob_corrupt") -> None:
        self.problems: List[str] = list(problems)
        self.code = code
        super().__init__("; ".join(self.problems) or "corrupt crate")


class DestinationNotEmpty(CrateError):
    """An extract destination that already exists."""

    code = "destination_exists"


class DestinationInsideHome(CrateError):

    code = "destination_inside_home"


class NeedsIdentity(CrateError):

    code = "needs_identity"


class WrongKey(CrateError):

    code = "wrong_key"


class ConversationNotInCrate(CrateError):
    """The conversation id named for an extract is not in the crate. Inputs: conversation_id."""

    code = "conversation_not_in_crate"

    def __init__(self, conversation_id: Optional[str]) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"conversation {conversation_id!r} is not in this crate")
