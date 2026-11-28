
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

import structlog

from src.core.computers import direction
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import roster_doc, roster_v2
from src.core.pack.relay import approval

log = structlog.get_logger(__name__)


def local_decides(*, target: str, self_id: str, content_alpha: Optional[str], master: Optional[str],
                  lst: Union[roster_doc.Roster, roster_v2.RosterV2, None], tls_row: bool) -> bool:
    return lst is None or self_id == content_alpha or target == master or (target not in lst.order() and not tls_row)


def decide(*, local: Optional[str], target: str, self_id: str, content_alpha: Optional[str], master: Optional[str],
           lst: Union[roster_doc.Roster, roster_v2.RosterV2, None], tls_row: bool, caps: Sequence[str]) -> bool:
    if local == approval.NO:
        return False
    if lst is None:
        return local == approval.YES
    signed = lst if isinstance(lst, roster_v2.RosterV2) else None
    if direction.listed_one_way(signed, target):
        return False
    if local_decides(target=target, self_id=self_id, content_alpha=content_alpha, master=master, lst=lst, tls_row=tls_row):
        return local == approval.YES
    entry = signed.entry(target) if signed is not None else None
    return entry is not None and entry.may_receive_logins and caps_mod.CAP_CREDENTIALS_MESH in caps


def local_no(open_db: Callable[[], sqlite3.Connection]) -> Callable[[str], bool]:
    def denied(install_id: str) -> bool:
        with closing(open_db()) as conn:
            return approval.answers(conn).get(install_id) == approval.NO
    return denied


def gate(open_db: Callable[[], sqlite3.Connection], caps_of: Callable[[str], Sequence[str]]) -> Callable[[str], bool]:
    plain = approval.reader(open_db)

    def approved(install_id: str) -> bool:
        if not caps_mod.mesh_on():
            return plain(install_id)
        from src.core.computers import store  # noqa: PLC0415
        from src.core.pack.machines import runtime as machines_runtime  # noqa: PLC0415
        wired = machines_runtime.wiring()
        if wired is None:
            return False
        with closing(open_db()) as conn:
            local = approval.answers(conn).get(install_id)
        if local == approval.NO:
            return False
        try:
            lst, content, master = _context(wired)
        except (OSError, ValueError) as exc:
            log.warning("pack_relay_login_gate_unreadable", error_type=type(exc).__name__)
            return False
        row = store.CACHE.get(install_id)
        return decide(local=local, target=install_id, self_id=wired.runtime.install_id, content_alpha=content, master=master,
                      lst=lst, tls_row=row is not None and row.transport == "tls", caps=list(caps_of(install_id)))
    return approved


def _context(wired: Any) -> Tuple[Union[roster_doc.Roster, roster_v2.RosterV2, None], Optional[str], Optional[str]]:
    custody = wired.runtime.custody
    held = custody.held_lists()
    return (held[0] if held else None), custody.content_alpha(), custody.settings().master_install_id


def list_state(wired: Any) -> Tuple[bool, Optional[str], Optional[Tuple[Any, Optional[str], Optional[str]]]]:
    try:
        context = _context(wired)
        return True, context[2], context
    except (OSError, ValueError) as exc:
        log.warning("pack_relay_card_unreadable", error_type=type(exc).__name__)
    try:
        return False, wired.runtime.custody.settings().master_install_id, None
    except (OSError, ValueError):
        return False, None, None


def card_rows(wired: Any, recorded: Dict[str, str], candidates: Sequence[str], context: Optional[Tuple[Any, Optional[str], Optional[str]]] = None) -> Dict[str, Any]:
    from src.core.computers import store  # noqa: PLC0415
    try:
        lst, content, master = context if context is not None else _context(wired)
    except (OSError, ValueError) as exc:
        log.warning("pack_relay_card_unreadable", error_type=type(exc).__name__)
        lst, content, master = None, None, None
    signed = lst if isinstance(lst, roster_v2.RosterV2) else None
    star = {p.install_id: p.label for p in wired.peers()}
    me = wired.runtime.install_id
    rows = []
    for iid in candidates:
        if lst is None and iid not in star:
            continue
        row = store.CACHE.get(iid)
        here = local_decides(target=iid, self_id=me, content_alpha=content, master=master, lst=lst,
                             tls_row=row is not None and row.transport == "tls")
        entry = signed.entry(iid) if signed is not None else None
        label = star.get(iid) or (entry.label if entry is not None and entry.label else "")
        if here:
            rows.append({"install_id": iid, "label": label, "answer": recorded.get(iid), "pending": iid not in recorded, "decided_by": "here"})
        else:
            yes = bool(entry is not None and entry.may_receive_logins and not direction.listed_one_way(signed, iid))
            rows.append({"install_id": iid, "label": label, "answer": approval.NO if recorded.get(iid) == approval.NO else None,
                         "pending": False, "decided_by": "alpha", "alpha_yes": yes})
    return {"computers": rows, "covers_pack": signed is not None and me == content}
