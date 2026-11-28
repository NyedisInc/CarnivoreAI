
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.computers import direction
from src.core.db import transaction
from src.core.pack.machines import capabilities
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.rollup_import import relay_store, signed, store, v2_export, v2_store
from src.core.pack.rollup_import.ddl import STATE_TABLE, purge_rows
from src.core.pack.rollup_import.relay_store import MAX_HOPS

logger = structlog.get_logger()

RELAY_KEY = "relay"
MAX_PAGES = 5000
MAX_ORIGINS = 64
STALE_SECONDS = 900.0


def advertised(snapshot: Any) -> Optional[int]:
    rev = snapshot.get("pipeline_rev") if isinstance(snapshot, dict) else None
    value = rev.get(RELAY_KEY) if isinstance(rev, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _valid_header(raw: Any, forwarder: str, self_id: str, lst: Any = None) -> Optional[Dict[str, Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for iid, entry in list(raw.items())[:MAX_ORIGINS]:
        if not (isinstance(iid, str) and 0 < len(iid) <= relay_store.MAX_ID_CHARS and isinstance(entry, dict)):
            continue
        hops = entry.get("hops")
        if not isinstance(hops, int) or isinstance(hops, bool) or not 1 <= hops or hops + 1 > MAX_HOPS:
            continue
        if iid in (self_id, forwarder) or direction.contained(iid):
            continue
        if lst is not None:
            if lst.entry(iid) is None or direction.listed_one_way(lst, iid):
                continue
        elif self_id in relay_store.id_list(entry.get("one_way")):
            continue
        out[iid] = entry
    return out


def _note_behind(imp: Any, conn: Any, forwarder: str, header: Dict[str, Dict[str, Any]], now: float) -> None:
    for origin, entry in header.items():
        held = relay_store.held_supplier(conn, origin)
        rev = entry.get("revision")
        if held is None or held[0] in ("", forwarder) or not isinstance(rev, int) or isinstance(rev, bool) or rev <= held[1]:
            continue
        first, best = imp.behind.get(origin, (now, rev))
        imp.behind[origin] = (first, max(best, rev))


def _pick(imp: Any, conn: Any, forwarder: str, origin: str, header: Dict[str, Dict[str, Any]], now: float) -> Optional[Tuple[str, int]]:
    entry = header.get(origin)
    behind = imp.behind.get(origin)
    held = relay_store.held_supplier(conn, origin) if behind is not None else None
    stale = behind is not None and held is not None and now - behind[0] >= STALE_SECONDS and held[0] not in imp._busy
    return relay_store.choose_supplier(conn, origin, direction.contained, members=imp.members, live=imp.live,
                                       offer=(forwarder, entry) if entry is not None else None, stale=stale)


def _first_page(imp: Any, forwarder: str, page: Dict[str, Any], since: int, known_digest: str, now: float, lst: Any = None,
                bad: frozenset = frozenset()) -> Optional[Tuple[Dict[str, Dict[str, Any]], bool]]:
    header = _valid_header(page.get("origins"), forwarder, imp._self_id, lst)
    if header is None:
        return None
    digest = page["scope_digest"]
    restart = False
    with closing(imp._open_db()) as conn, transaction(conn):
        if not relay_store.supplier_ok(conn, forwarder, imp.members):
            return None
        _note_behind(imp, conn, forwarder, header, now)
        if page.get("reset") is True or (bool(known_digest) and digest != known_digest):
            for origin in relay_store.origins_via(conn, forwarder):
                held = store.get_state(conn, origin)
                store.reset_origin(conn, origin, "", now, via=forwarder, hops=held.hops if held is not None else 2, members=imp.members)
            restart = page.get("reset") is not True and since != 0
        relay_store.record_offers(conn, forwarder, {iid: entry["hops"] for iid, entry in header.items()}, now)
        for origin in relay_store.origins_via(conn, forwarder):
            best = _pick(imp, conn, forwarder, origin, header, now)
            if origin in header and best is not None and best[0] == forwarder:
                continue
            purge_rows(conn, origin, keep_floor=True)
            if best is not None and best[0] not in ("", forwarder):
                relay_store.set_relay_state(conn, best[0], 0, "", now)
        accepted: Dict[str, Dict[str, Any]] = {}
        for origin, entry in header.items():
            best = _pick(imp, conn, forwarder, origin, header, now)
            if best is None or best[0] != forwarder or origin in bad:
                continue
            accepted[origin] = entry
            held = store.get_state(conn, origin)
            if held is None or held.via != forwarder:
                if store.reset_origin(conn, origin, "", now, via=forwarder, hops=best[1], members=imp.members):
                    imp.behind.pop(origin, None)
                restart = restart or since != 0
    return accepted, restart


def _apply(imp: Any, forwarder: str, groups: List[Any], accepted: Dict[str, Dict[str, Any]], verified: Optional[signed.Verified] = None) -> Optional[int]:
    by_origin: Dict[str, List[Any]] = {}
    for group in groups:
        if group["origin"] in accepted:
            by_origin.setdefault(group["origin"], []).append(group)
    applied = 0
    with closing(imp._open_db()) as conn:
        for origin, items in by_origin.items():
            proofs = None if verified is None else {(cid, hour): proof for (o, cid, hour), proof in verified.items() if o == origin}
            done = store.apply_page(conn, origin, items, via=forwarder, signed=proofs, members=imp.members)
            if done is None:
                return None
            applied += done
    return applied


def _finish(imp: Any, forwarder: str, until: int, digest: str, accepted: Dict[str, Dict[str, Any]], now: float,
            name_proofs: Optional[Dict[str, signed.Proof]] = None, advance: bool = True,
            v2_proofs: Optional[Dict[str, signed.Proof]] = None) -> bool:
    with closing(imp._open_db()) as conn, transaction(conn):
        if not relay_store.supplier_ok(conn, forwarder, imp.members):
            return False
        for origin, entry in accepted.items():
            held = store.get_state(conn, origin)
            if held is None or held.via != forwarder:
                continue
            rev, pulled = entry.get("revision"), entry.get("pulled_at")
            rev_int = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
            label = entry.get("label")
            conn.execute(
                f"UPDATE {STATE_TABLE} SET revision = ?, scope_digest = ?, label = ?, one_way = ?, hops = ?, origin_pulled_at = ?, "
                "pulled_at = ?, updated_at = ? WHERE peer_install_id = ? AND via = ?",
                (rev_int,
                 entry.get("scope_digest") if isinstance(entry.get("scope_digest"), str) else "",
                 label[:64] if isinstance(label, str) and label else None,
                 json.dumps(relay_store.id_list(entry.get("one_way"))), entry["hops"] + 1,
                 float(pulled) if isinstance(pulled, (int, float)) and not isinstance(pulled, bool) else 0.0, now, now, origin, forwarder))
            behind = imp.behind.get(origin)
            if behind is not None and isinstance(rev, int) and not isinstance(rev, bool) and rev >= behind[1]:
                imp.behind.pop(origin, None)
            if name_proofs is not None:
                if origin in name_proofs:
                    relay_store.replace_names_signed(conn, origin, entry.get("names"), entry.get("homes"), *name_proofs[origin])
            elif "names" in entry or "homes" in entry:
                relay_store.replace_names(conn, origin, entry.get("names"), entry.get("homes"))
            if v2_proofs is not None:
                if origin in v2_proofs:
                    v2_store.apply_v2_signed(conn, origin, entry.get("v2"), *v2_proofs[origin], now=now)
            elif "v2" in entry:
                v2_store.apply_v2(conn, origin, entry.get("v2"), rev=rev_int, now=now)
        if advance:
            relay_store.set_relay_state(conn, forwarder, until, digest, now)
    return True


def _verify_page(imp: Any, forwarder: str, page: Dict[str, Any], first: bool, lst: Any
                 ) -> Optional[Tuple[signed.Verified, Dict[str, signed.Proof], Dict[str, signed.Proof], set]]:
    header = _valid_header(page["origins"], forwarder, imp._self_id, lst)
    if header is None:
        return None
    by_origin: Dict[str, List[Any]] = {}
    for group in page["groups"]:
        if group["origin"] in header:
            by_origin.setdefault(group["origin"], []).append(group)
    verified: signed.Verified = {}
    proofs: Dict[str, signed.Proof] = {}
    v2_proofs: Dict[str, signed.Proof] = {}
    bad: set = set()
    for origin, entry in header.items():
        got = signed.verify_groups(by_origin.get(origin, []), lambda g: g["origin"], lst, relay=True)
        proof = None
        if got is not None and first and any(key in entry for key in ("names", "homes", "names_rev", "names_sig", "names_epoch")):
            proof = signed.verify_names(origin, entry.get("names"), entry.get("homes", {}), entry.get("names_rev"), entry.get("names_sig"), lst, entry.get("names_epoch"))
            got = None if proof is None else got
        v2_proof = None
        if got is not None and first and any(key in entry for key in ("v2", "v2_rev", "v2_epoch", "v2_sig")):
            v2_proof = v2_export.verify_v2(
                origin, entry.get("v2"), entry.get("v2_rev"), entry.get("v2_sig"), lst, entry.get("v2_epoch")
            )
            got = None if v2_proof is None else got
        if got is None:
            bad.add(origin)
            continue
        verified.update(got)
        if proof is not None:
            proofs[origin] = proof
        if v2_proof is not None:
            v2_proofs[origin] = v2_proof
    return verified, proofs, v2_proofs, bad


async def pull_relay(imp: Any, forwarder: str, post: Any) -> None:
    since, known_digest = await asyncio.to_thread(lambda: _read_state(imp, forwarder))
    lst: Any = None
    if capabilities.mesh_on():
        lst = await asyncio.to_thread(imp.held_list)
        if not isinstance(lst, RosterV2):
            imp._note_once(forwarder, "relay_no_list")
            return
    want_v2 = capabilities.has(imp._caps(forwarder), capabilities.CAP_ROLLUP_V2)
    verified: Optional[signed.Verified] = None
    name_proofs: Optional[Dict[str, signed.Proof]] = {} if lst is not None else None
    v2_proofs: Optional[Dict[str, signed.Proof]] = {} if lst is not None else None
    until: Optional[int] = None
    cursor: Optional[str] = None
    started_digest = ""
    accepted: Dict[str, Dict[str, Any]] = {}
    bad: set = set()
    for _ in range(MAX_PAGES):
        page = await imp._page(post, since, until, cursor, stream="relay", v2=want_v2)
        if page is None or page.get("available") is False:
            imp._note_once(forwarder, "relay_unavailable", reason=(page or {}).get("reason", "refused"))
            return
        digest, groups, page_until = page.get("scope_digest"), page.get("groups"), page.get("until_revision")
        if not (page.get("stream") == "relay" and isinstance(digest, str) and isinstance(groups, list) and isinstance(page_until, int)
                and isinstance(page.get("origins"), dict)
                and all(isinstance(g, dict) and isinstance(g.get("origin"), str) and 0 < len(g["origin"]) <= relay_store.MAX_ID_CHARS for g in groups)):
            imp._note_once(forwarder, "relay_malformed")
            return
        if lst is not None:
            checked = await asyncio.to_thread(_verify_page, imp, forwarder, page, until is None, lst)
            if checked is None:
                imp._note_once(forwarder, "relay_header_unusable")
                return
            verified = checked[0]
            if until is None:
                name_proofs = checked[1]
                v2_proofs = checked[2]
            if checked[3]:
                bad |= checked[3]
                imp._note_once(forwarder, "relay_forged")
        if until is None:
            decided = await asyncio.to_thread(_first_page, imp, forwarder, page, since, known_digest, imp._clock(), lst, frozenset(bad))
            if decided is None:
                imp._note_once(forwarder, "relay_header_unusable")
                return
            accepted, restart = decided
            known_digest = digest
            if restart:
                since, until, cursor = 0, None, None
                continue
            until, started_digest = page_until, digest
        accepted = {origin: entry for origin, entry in accepted.items() if origin not in bad}
        applied = await asyncio.to_thread(_apply, imp, forwarder, groups, accepted, verified)
        if applied is None:
            return
        if page.get("complete") is True:
            await asyncio.to_thread(_finish, imp, forwarder, until, started_digest, accepted, imp._clock(), name_proofs, not bad, v2_proofs)
            logger.debug("pack_rollup_relay_pulled", peer=forwarder[:8], revision=until, origins=len(accepted))
            return
        nxt = page.get("next_cursor")
        if not isinstance(nxt, str) or not nxt or nxt == cursor:
            imp._note_once(forwarder, "relay_bad_cursor")
            return
        cursor = nxt
    imp._note_once(forwarder, "relay_too_many_pages")


def _read_state(imp: Any, forwarder: str) -> Tuple[int, str]:
    with closing(imp._open_db()) as conn:
        return relay_store.get_relay_state(conn, forwarder)
