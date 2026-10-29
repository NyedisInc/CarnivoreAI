
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class LoadoutMemberPreview(BaseModel):
    """One item a loadout lists, as the INSTALL SHEET reads it.

    THE IDENTITY COMES FROM THE MANIFEST AND EVERYTHING ELSE IS
    MEASURED. A loadout's ``loadout.json`` says which items it wants; it
    cannot say what those items are, and it must never be believed about
    them. So ``kind``, ``scripts`` and ``installed`` are read from the
    verified INDEX and the local ledger, not from the list, because they
    are what the sheet uses to tell the user what they are about to get
    and which members will ask for a tick of their own.
    """

    item_id: str
    version: str
    kind: str
    title: Optional[str] = None
    scripts: int = 0
    installed: bool = False
    instructions_write: bool = False
    instructions_details: List[str] = []
    instructions_more: int = 0


class LoadoutMemberView(BaseModel):
    """What actually happened to one member of an installed loadout.

    Fields:
        item_id, version: which member, at which pinned version.
        state: ``installed``, ``already_present`` or ``refused``.
        code, detail: present ONLY for ``refused``, naming which refusal
            and why. A partial that cannot say which member failed, and
            for what reason, is not actionable.
        install_id: the member's own ledger id when it has one, which is
            what an offer to remove it later is addressed by.
    """

    item_id: str
    version: str
    state: str
    code: Optional[str] = None
    detail: Optional[str] = None
    install_id: Optional[str] = None
