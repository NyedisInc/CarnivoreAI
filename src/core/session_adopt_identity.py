"""What to call a session the user just opened: its stored id, or a new one.

The pure decision behind ``SessionManager.adopt_external_session``'s very
first line. It used to be a literal::

    adopted_id = f"adopted:{name}"

and that literal is a defect whenever the session ALREADY HAS A ROW.

WHAT IS STILL DERIVED, and must stay that way. A genuinely external
session - one with no row for its instance triple - has no stored id to
recover, and ``adopted:<name>`` remains exactly right for it. So does a
session whose creation epoch could not be read: with no epoch there is no
instance triple, ``session_store.get_instance`` returns None BY CONTRACT,
and a row that merely shares the NAME describes some other, historical
process. Guessing there would attach a stranger's row to a live pane,
which is a worse failure than a fresh id.

A RECOVERED ID CARRIES A CREDENTIAL; A DERIVED ONE DOES NOT. That is the
whole reason :attr:`AdoptIdentity.rekeyed` exists as a field rather than
being re-derived by the caller from a string prefix. The caller mints a
hook token for a derived id and MUST NOT mint one for a recovered id -
minting rotates the token, and rotating the token is precisely the 403
this module exists to stop. See ``HookTokenAuthority.keep``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import structlog

from src.core.session_boot_readopt_plan import (
    ID_SOURCE_DERIVED,
    derived_id_for,
    resolve_session_id,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "AdoptIdentity",
    "resolve_adopt_identity",
]


@dataclass(frozen=True)
class AdoptIdentity:

    session_id: str
    id_source: str
    rekeyed: bool

    def log_if_rekeyed(self, name: str) -> None:
        if self.rekeyed:
            logger.info(
                "adopt_rekeyed_to_stored_id",
                session=name,
                session_id=self.session_id,
                id_source=self.id_source,
                note=(
                    "this session already had a row, so it is registered "
                    "under the id its agent presents on hooks rather than "
                    "a fresh adopted: id"
                ),
            )


def resolve_adopt_identity(
    *,
    name: str,
    epoch: Optional[int],
    row_lookup: Callable[[str, Optional[int]], Optional[Dict[str, Any]]],
    hook_names: Dict[str, str],
) -> AdoptIdentity:
    """Decide whether an adoption re-keys to a stored id or mints a new one.

    Description: pure - no tmux, no sqlite, no event loop. The caller
      supplies the instance-triple read as ``row_lookup`` (in production
      ``session_store.get_instance``, the SAME lookup the boot re-adopt
      plan uses) so this whole decision is testable without a socket.

      Two guards ahead of the ladder, and both answer "derive" rather
      than guess. A missing epoch identifies no instance at all. A
      missing row means nothing durable describes this pane, which is
      the ordinary true-external adoption and not a failure.
    Inputs: name (str) - literal tmux session name. epoch (int | None) -
      the instance's ``#{session_created}``, as measured by the adopt
      persistence step; None when the listing could not supply one.
      row_lookup (callable) - ``(name, epoch) -> sessions row | None``.
      hook_names (dict[str, str]) - session_id -> tmux name, as restored
      by ``HookTokenAuthority.load``.
    Output: AdoptIdentity.
    Example: resolve_adopt_identity(name='cloude_a', epoch=1000,
                 row_lookup=f, hook_names={'ses_1': 'cloude_a'}).session_id
             # 'ses_1'
    """
    if epoch is None:
        return AdoptIdentity(derived_id_for(name), ID_SOURCE_DERIVED, False)

    row = row_lookup(name, epoch)
    if row is None:
        return AdoptIdentity(derived_id_for(name), ID_SOURCE_DERIVED, False)

    session_id, id_source = resolve_session_id(name, row, hook_names)
    return AdoptIdentity(
        session_id, id_source, id_source != ID_SOURCE_DERIVED
    )
