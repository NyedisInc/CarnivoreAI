
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.core.crate_import.model import FOREIGN, OWN_VERIFIED
from src.core.db import get_meta
from src.core.exports.store import crate_written_key

R_WRITTEN_HERE = "written_here"
R_OWNER_SAID = "owner_attested"
R_CLAIMS_NOT_PROVEN = "claims_this_computer_not_proven"
R_OTHER_COMPUTER = "other_computer"
R_NO_INSTALL = "no_install_id"
R_MARK_DIFFERS = "mark_differs"
R_SHARE_CRATE = "share_crate"


@dataclass(frozen=True)
class Provenance:

    kind: str
    reason: str
    claims_this_install: bool

    @property
    def own(self) -> bool:
        return self.kind == OWN_VERIFIED


def provenance_of(conn: sqlite3.Connection, manifest_source: Mapping[str, Any], bundle_id: str, crate_sha256: str,
                  install_id: Optional[str], *, made_here: bool = False, share: bool = False) -> Provenance:
    if share:
        return Provenance(FOREIGN, R_SHARE_CRATE, False)
    claimed = manifest_source.get("install_id")
    if not install_id:
        return Provenance(FOREIGN, R_NO_INSTALL, False)
    claims = isinstance(claimed, str) and claimed == install_id
    if not claims:
        return Provenance(FOREIGN, R_OTHER_COMPUTER, False)
    mark = get_meta(conn, crate_written_key(bundle_id))
    if mark is not None and mark == crate_sha256:
        return Provenance(OWN_VERIFIED, R_WRITTEN_HERE, True)
    if made_here:
        return Provenance(OWN_VERIFIED, R_OWNER_SAID, True)
    return Provenance(FOREIGN, R_MARK_DIFFERS if mark is not None else R_CLAIMS_NOT_PROVEN, True)
