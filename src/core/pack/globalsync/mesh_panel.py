
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Collection, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.pack.globalsync import fracindex, mesh_panel_doc as doc_mod, panel, panel_apply, panel_merge
from src.core.pack.machines import config_state
from src.core.pack.meshdata import hlc, panel_kind


class MeshPanelError(ValueError):
    pass


log = structlog.get_logger(__name__)

SEEN_FILE = "mesh-panel-seen.json"
KIND = panel_kind.KIND
_LAST_REFUSED = {"count": 0}


class Seen:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.store_id: Optional[str] = None
        self.scalars: Dict[str, str] = {}
        self.lists: Dict[str, List[List[Any]]] = {}
        self.lm_bc: Dict[str, Dict[str, bool]] = {}
        self._loaded = ""

    def _payload(self) -> str:
        body: Dict[str, Any] = {"v": 1, "store_id": self.store_id, "scalars": self.scalars, "lists": self.lists}
        if self.lm_bc:
            body["lm_bc"] = self.lm_bc
        return json.dumps(body, sort_keys=True)

    @classmethod
    def load(cls, path: Path) -> "Seen":
        seen = cls(path)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            scalars, lists = raw["scalars"], raw["lists"]
            if (isinstance(scalars, dict) and isinstance(lists, dict) and all(isinstance(v, str) for v in scalars.values())
                    and all(isinstance(rows, list) and all(isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) for r in rows) for rows in lists.values())):
                seen.store_id = raw["store_id"] if isinstance(raw.get("store_id"), str) else None
                seen.scalars, seen.lists = scalars, lists
                raw_bc = raw.get("lm_bc")
                if isinstance(raw_bc, dict):
                    seen.lm_bc = {
                        lid: {k: v for k, v in flags.items() if isinstance(k, str) and isinstance(v, bool)}
                        for lid, flags in raw_bc.items()
                        if isinstance(lid, str) and isinstance(flags, dict)
                    }
        except (OSError, ValueError, KeyError, TypeError):
            pass
        seen._loaded = seen._payload()
        return seen

    def save(self) -> None:
        text = self._payload()
        if text != self._loaded and atomic_write_json(self.path, json.loads(text), log_event="mesh_panel_seen_write_failed"):
            self._loaded = text

    def groups(self) -> Set[str]:
        out = {k.split(":")[1] for k in self.scalars if k.startswith("g:")}
        return out | {lid[3:] for lid in self.lists if lid.startswith(("gm.", "gb."))}

    def companies(self) -> Set[str]:
        return {k.split(":")[1] for k in self.scalars if k.startswith("c:")}

    def layouts(self) -> Set[str]:
        out = {k.split(":")[1] for k in self.scalars if k.startswith("ly:")}
        return out | {lid[3:] for lid in self.lists if lid.startswith("lm.")}

    def items(self) -> List[str]:
        return [item for rows in self.lists.values() for item, _pos in rows]


class Ctx:

    def __init__(self, store: Any, signing: Any, lst: Any, own: str, legacy_path: Path, gen: Optional[int] = None) -> None:
        self.store, self.signing, self.lst, self.own, self.legacy_path, self.gen = store, signing, lst, own, legacy_path, gen
        self.privileged = own in (lst.alpha, lst.home)

    def moved(self) -> bool:
        return self.gen is not None and self.store.generation != self.gen


def _flatten(conn: sqlite3.Connection, ctx: Ctx, arrangement: Optional[Mapping[str, Any]], rows: doc_mod.Rows, seen: Seen
             ) -> Tuple[Dict[str, Any], doc_mod.Scalars, doc_mod.Lists]:
    known_groups = {u: (rows[f"g:{u}:gone"][1].ms if f"g:{u}:gone" in rows else 0) for u in seen.groups()}
    known_companies = {u: (rows[f"c:{u}:gone"][1].ms if f"c:{u}:gone" in rows else 0) for u in seen.companies()}
    known_layouts = {u: (rows[f"ly:{u}:gone"][1].ms if f"ly:{u}:gone" in rows else 0) for u in seen.layouts()}
    store_items = [k.split(":", 2)[2] for k in rows if k.startswith("l:")]
    doc = doc_mod.local_doc(conn, arrangement, ctx.own, [*store_items, *seen.items()], known_groups, known_companies, known_layouts)
    scalars, lists = doc_mod.flatten_doc(doc)
    return doc, scalars, lists


def _local_projects_fingerprint(conn: sqlite3.Connection) -> str:
    uids = [r[0] for r in conn.execute("SELECT uid FROM projects WHERE uid IS NOT NULL ORDER BY uid")]
    return hashlib.sha1("\n".join(uids).encode("utf-8")).hexdigest()[:16]


def _member_keys(ctx: Ctx, keys: Collection[str], rows: doc_mod.Rows) -> FrozenSet[str]:
    fresh = [k for k in keys if k not in rows]
    if not ctx.privileged or not fresh:
        return frozenset()
    fields = panel_merge.Ledger(ctx.legacy_path).fields
    return frozenset(k for k in fresh if fields.get(doc_mod.legacy_field(k), [0, "", ""])[1] not in ("", ctx.own))


def _put(ctx: Ctx, items: List[Tuple[str, Any, Optional[hlc.Stamp]]], member: Collection[str]) -> int:
    if not items:
        return 0
    _written, refused = ctx.store.put_many(KIND, items, ctx.signing, ctx.lst, member_keys=member, gen=ctx.gen)
    if refused != _LAST_REFUSED["count"]:
        log.info("mesh_panel_room_refused", count=refused)
        _LAST_REFUSED["count"] = refused
    return refused


def _confirmed(rows: doc_mod.Rows, key: str, value: Any) -> bool:
    return key in rows and rows[key][0] == value


def _store_pos(rec: Mapping[str, Tuple[Optional[str], hlc.Stamp]], item: str) -> Optional[str]:
    return rec[item][0] if item in rec else None


def item_synced(list_id: str, item: str) -> bool:
    return doc_mod.item_ok(list_id, item)


def _plan_list(list_id: str, cur_all: List[str], prev: List[List[Any]], rec: Mapping[str, Tuple[Optional[str], hlc.Stamp]]
               ) -> Tuple[Dict[str, Optional[str]], Dict[str, str]]:
    prev_pos = {i: p for i, p in prev}
    live = [i for i in cur_all if item_synced(list_id, i) and not (i in prev_pos and i in rec and rec[i][0] is None)]
    base: List[Optional[str]] = [prev_pos[i] if prev_pos.get(i) is not None else _store_pos(rec, i) for i in live]
    skip = {i for i, b in zip(live, base) if b is None and i in prev_pos}
    keep = doc_mod.lis_keep(base)
    puts: Dict[str, Optional[str]] = {}
    kept: Dict[str, str] = {i: b for n, (i, b) in enumerate(zip(live, base)) if n in keep and b is not None}
    try:
        n, total = 0, len(live)
        while n < total:
            if n in keep or live[n] in skip:
                n += 1
                continue
            end = n
            while end < total and end not in keep and live[end] not in skip:
                end += 1
            left = next((base[k] for k in range(n - 1, -1, -1) if k in keep), None)
            right = next((base[k] for k in range(end, total) if k in keep), None)
            key = left
            for i in live[n:end]:
                key = fracindex.key_between(key, right)
                puts[i] = key
            n = end
        if any(fracindex.needs_rebalance(k) for k in puts.values() if k):
            raise MeshPanelError("rebalance")
    except ValueError:
        puts = {i: fracindex.seed(n, len(live)) for n, i in enumerate(live) if i not in skip}
        kept = {}
    for item, _pos in prev:
        if item in cur_all or (item in rec and rec[item][0] is None) or (prev_pos.get(item) is None and item not in rec):
            continue
        puts[item] = None
    return puts, kept


def observe(
    ctx: Ctx,
    seen: Seen,
    scalars: doc_mod.Scalars,
    lists: doc_mod.Lists,
    shadow: Collection[str],
    rows: doc_mod.Rows,
    local_bc: Optional[Mapping[str, Mapping[str, bool]]] = None,
) -> Set[str]:
    items: List[Tuple[str, Any, Optional[hlc.Stamp]]] = []
    s_hash: Dict[str, str] = {}
    for key, value in scalars.items():
        h = doc_mod.value_hash(value)
        if seen.scalars.get(key) == h or not panel_kind.valid(key, value):
            continue
        if (key not in seen.scalars and key.startswith("p:") and key.split(":")[1] in shadow) or (key in rows and rows[key][0] == value):
            seen.scalars[key] = h
            continue
        items.append((key, value, None))
        s_hash[key] = h
    plans: Dict[str, Tuple[Dict[str, Optional[str]], Dict[str, str]]] = {}
    _s, store_l = doc_mod.split_rows(rows)
    store_bc = doc_mod.split_row_bc(rows)
    bc_map = local_bc or {}
    bc_puts: Dict[str, Dict[str, bool]] = {}
    for list_id in sorted(set(lists) | set(seen.lists)):
        plans[list_id] = _plan_list(list_id, lists.get(list_id, []), seen.lists.get(list_id, []), store_l.get(list_id, {}))
        puts, kept = plans[list_id]
        if list_id.startswith("lm."):
            cur_bc = bc_map.get(list_id, {})
            prev_bc = seen.lm_bc.get(list_id, {})
            rec_bc = store_bc.get(list_id, {})
            for i, pos in puts.items():
                if pos is None:
                    items.append((f"l:{list_id}:{i}", {"pos": None}, None))
                else:
                    flag = bool(cur_bc.get(i, True))
                    items.append((f"l:{list_id}:{i}", {"pos": pos, "bc": flag}, None))
                    bc_puts.setdefault(list_id, {})[i] = flag
            for i, pos in kept.items():
                if i in puts:
                    continue
                flag = bool(cur_bc.get(i, True))
                if flag != prev_bc.get(i, True):
                    if rec_bc.get(i, True) != flag:
                        items.append((f"l:{list_id}:{i}", {"pos": pos, "bc": flag}, None))
                        bc_puts.setdefault(list_id, {})[i] = flag
                    else:
                        seen.lm_bc.setdefault(list_id, {})[i] = flag
        else:
            items.extend((f"l:{list_id}:{i}", {"pos": pos}, None) for i, pos in puts.items())
    _put(ctx, items, _member_keys(ctx, [k for k, _v, _s2 in items], rows))
    fresh = ctx.store.kind_rows(ctx.lst, KIND) if items else rows
    refused: Set[str] = set()
    for key, h in s_hash.items():
        if _confirmed(fresh, key, scalars[key]):
            seen.scalars[key] = h
        else:
            refused.add(key)
    for key in [k for k in seen.scalars if k not in scalars]:
        del seen.scalars[key]
    _s2, fresh_l = doc_mod.split_rows(fresh)
    fresh_bc = doc_mod.split_row_bc(fresh)
    for list_id, (puts, kept) in plans.items():
        prev = seen.lists.get(list_id, [])
        prev_pos = {i: p for i, p in prev}
        rec = fresh_l.get(list_id, {})
        out: List[List[Any]] = []
        for item in lists.get(list_id, []):
            if not item_synced(list_id, item):
                continue
            if puts.get(item) is not None and item in rec and rec[item][0] == puts[item]:
                out.append([item, puts[item]])
            elif item in kept:
                out.append([item, kept[item]])
            elif item in prev_pos:
                out.append([item, prev_pos[item]])
        out += [[item, pos] for item, pos in prev if puts.get(item, 0) is None and not (item in rec and rec[item][0] is None)]
        if out:
            seen.lists[list_id] = out
            if list_id.startswith("lm."):
                cur_bc = bc_map.get(list_id, {})
                prev_bc = seen.lm_bc.get(list_id, {})
                f_bc = fresh_bc.get(list_id, {})
                b_puts = bc_puts.get(list_id, {})
                next_bc: Dict[str, bool] = {}
                for item, _pos in out:
                    if item in b_puts:
                        if item in f_bc and f_bc[item] == b_puts[item]:
                            next_bc[item] = b_puts[item]
                        elif item in prev_bc:
                            next_bc[item] = prev_bc[item]
                    elif item in prev_bc:
                        next_bc[item] = prev_bc[item]
                    else:
                        next_bc[item] = bool(f_bc.get(item, cur_bc.get(item, True)))
                seen.lm_bc[list_id] = next_bc
        else:
            seen.lists.pop(list_id, None)
            seen.lm_bc.pop(list_id, None)
    return refused


def rebase(
    seen: Seen,
    scalars: doc_mod.Scalars,
    lists: doc_mod.Lists,
    rows: doc_mod.Rows,
    *,
    scalars_too: bool,
    local_bc: Optional[Mapping[str, Mapping[str, bool]]] = None,
) -> None:
    _s, store_l = doc_mod.split_rows(rows)
    store_bc = doc_mod.split_row_bc(rows)
    bc_map = local_bc or {}
    if scalars_too:
        seen.scalars = {k: doc_mod.value_hash(v) for k, v in scalars.items() if panel_kind.valid(k, v)}
    elif "a:sections" in scalars and panel_kind.valid("a:sections", scalars["a:sections"]):
        seen.scalars["a:sections"] = doc_mod.value_hash(scalars["a:sections"])
    prev = {lid: dict(rows_) for lid, rows_ in seen.lists.items()}
    lists_now: Dict[str, List[List[Any]]] = {}
    bc_now: Dict[str, Dict[str, bool]] = {}
    for lid, items in lists.items():
        rec = store_l.get(lid, {})
        out: List[List[Any]] = []
        for item in items:
            if not item_synced(lid, item):
                continue
            if item in rec:
                out.append([item, _store_pos(rec, item)])
            elif scalars_too:
                out.append([item, None])
            elif item in prev.get(lid, {}):
                out.append([item, prev[lid][item]])
        if out:
            lists_now[lid] = out
            if lid.startswith("lm."):
                s_bc = store_bc.get(lid, {})
                l_bc = bc_map.get(lid, {})
                bc_now[lid] = {item: bool(s_bc[item] if item in s_bc else l_bc.get(item, True)) for item, _pos in out}
    seen.lists = lists_now
    seen.lm_bc = bc_now


def _clamp(ms: int) -> int:
    return max(1, min(ms, int(time.time() * 1000)))


def seed(ctx: Ctx, seen: Seen, doc: Mapping[str, Any], scalars: doc_mod.Scalars, lists: doc_mod.Lists, shadow: Collection[str], rows: doc_mod.Rows) -> int:
    ledger = panel_merge.Ledger(ctx.legacy_path).fields
    now = doc_mod.legacy_hashes(doc)
    local_bc = doc_mod.layout_member_bc(doc)
    alpha = ctx.own == ctx.lst.alpha
    items: List[Tuple[str, Any, Optional[hlc.Stamp]]] = []
    member: Set[str] = set()
    pending: Set[str] = set()

    def decide(key: str) -> Optional[int]:
        field = doc_mod.legacy_field(key)
        row, cur = ledger.get(field), now.get(field)
        if cur is None:
            return None
        if row is None:
            return 1 if alpha else None
        if row[2] != cur:
            pending.add(field)
            return None
        if alpha or (row[1] == ctx.own and row[0] > 0):
            if row[1] not in ("", ctx.own):
                member.add(key)
            return _clamp(row[0])
        return None

    for key, value in scalars.items():
        ms = decide(key) if panel_kind.valid(key, value) else None
        if ms is not None and not (ms == 1 and key.startswith("p:") and key.split(":")[1] in shadow):
            items.append((key, value, hlc.Stamp(ms, 0, ctx.own)))
    for list_id, members in lists.items():
        present = [i for i in members if item_synced(list_id, i)]
        for n, item in enumerate(present):
            ms = decide(f"l:{list_id}:{item}")
            if ms is not None:
                val: Dict[str, Any] = {"pos": fracindex.seed(n, len(present))}
                if list_id.startswith("lm."):
                    val["bc"] = bool(local_bc.get(list_id, {}).get(item, True))
                items.append((f"l:{list_id}:{item}", val, hlc.Stamp(ms, 0, ctx.own)))
    guard = frozenset(k for k in member if k not in rows) if ctx.privileged else frozenset()
    written = ctx.store.put_many(KIND, items, ctx.signing, ctx.lst, member_keys=guard, gen=ctx.gen)[0] if items else 0
    fresh = ctx.store.kind_rows(ctx.lst, KIND)
    rebase(seen, scalars, lists, fresh, scalars_too=True, local_bc=local_bc)
    refused = {k for k, _v, _s in items if k.startswith("l:") and k not in fresh}
    for list_id in list(seen.lists):
        kept = [r for r in seen.lists[list_id] if not (r[1] is None and f"l:{list_id}:{r[0]}" in refused)]
        if kept:
            seen.lists[list_id] = kept
        else:
            del seen.lists[list_id]
            seen.lm_bc.pop(list_id, None)
    for key in [k for k in seen.scalars if doc_mod.legacy_field(k) in pending]:
        del seen.scalars[key]
    for list_id in [lid for lid in seen.lists if doc_mod.legacy_field(f"l:{lid}:x") in pending]:
        del seen.lists[list_id]
        seen.lm_bc.pop(list_id, None)
    seen.store_id = ctx.store.store_id()
    return written


def _arrangement_of(read: Any) -> Optional[Mapping[str, Any]]:
    return ((read or {}).get("values") or {}).get("drawer_arrangement") if isinstance(read, Mapping) else None


def _may_apply(ctx: Ctx) -> bool:
    return ctx.privileged or bool(config_state.default().restrictions().may_receive_pack_ui)


def attach(app_state: Any, open_db: Callable[[], Any], settings: Callable[[], Mapping[str, Any]], legacy_path: Path) -> Callable[[Any, Any], Any]:
    seen_path = Path(legacy_path).parent / SEEN_FILE
    state: Dict[str, Optional[str]] = {"digest": None}

    def work(service: Any, lst: Any) -> Optional[Tuple[Dict[str, Any], Any]]:
        ui_store = app_state.ui_preferences_store
        ctx = Ctx(service.store, service.signing, lst, service.store.own_iid, Path(legacy_path), service.pass_gen)
        with panel_merge.LOCK:
            seen = Seen.load(seen_path)
            if ctx.moved():
                return None

            def view(conn: sqlite3.Connection, arrangement: Optional[Mapping[str, Any]]) -> Tuple[Dict[str, Any], doc_mod.Scalars, doc_mod.Lists, Set[str], doc_mod.Rows]:
                rows = ctx.store.kind_rows(lst, KIND)
                doc, scalars, lists = _flatten(conn, ctx, arrangement, rows, seen)
                return doc, scalars, lists, panel_merge.shadow_uids(conn), rows

            def read_view() -> Tuple[Dict[str, Any], doc_mod.Scalars, doc_mod.Lists, Set[str], doc_mod.Rows]:
                arrangement = _arrangement_of(ui_store.read())
                with closing(open_db()) as conn:
                    conn.execute("BEGIN")
                    try:
                        return view(conn, arrangement)
                    finally:
                        conn.execute("ROLLBACK")

            def local_projects_fp() -> str:
                with closing(open_db()) as conn:
                    return _local_projects_fingerprint(conn)

            sid = ctx.store.store_id()
            if seen.store_id != sid:
                doc, scalars, lists, shadow, rows = read_view()
                seed(ctx, seen, doc, scalars, lists, shadow, rows)
                if not ctx.moved():
                    seen.save()
                return None
            digest = f"{ctx.store.kind_digest(lst, KIND)}:{local_projects_fp()}"
            if not (_may_apply(ctx) and digest != state["digest"]):
                doc, scalars, lists, shadow, rows = read_view()
                observe(ctx, seen, scalars, lists, shadow, rows, doc_mod.layout_member_bc(doc))
                if not ctx.moved():
                    seen.save()
                return None
            applied: Dict[str, Any] = {}

            def compute(conn: sqlite3.Connection, iid: str, current: Any) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
                doc, scalars, lists, shadow, rows = view(conn, current)
                local_bc = doc_mod.layout_member_bc(doc)
                held = observe(ctx, seen, scalars, lists, shadow, rows, local_bc)
                fresh = ctx.store.kind_rows(lst, KIND)
                report, arrangement = panel.apply(conn, doc_mod.build_doc(scalars, lists, fresh, held, local_bc), iid, current, None)
                applied["digest"] = f"{ctx.store.kind_digest(lst, KIND)}:{_local_projects_fingerprint(conn)}"
                _post, p_scalars, _p_lists = _flatten(conn, ctx, arrangement, fresh, seen)
                seen.scalars.update({k: doc_mod.value_hash(v) for k, v in p_scalars.items() if panel_kind.valid(k, v) and k not in held and k != "a:sections"})
                return report, arrangement

            def after_commit(conn: sqlite3.Connection, committed: Any, iid: str) -> None:
                rows = ctx.store.kind_rows(lst, KIND)
                doc, scalars, lists = _flatten(conn, ctx, committed, rows, seen)
                rebase(seen, scalars, lists, rows, scalars_too=False, local_bc=doc_mod.layout_member_bc(doc))
                applied["rebased"] = True

            report, arr, result = panel_apply.run_locked(ui_store, open_db, compute, after_commit)
            if not ctx.moved():
                seen.save()
            if arr is not None and not applied.get("rebased"):
                log.warning("mesh_panel_apply_rejected", status=getattr(result, "status", None))
            state["digest"] = applied["digest"]
            return report, result

    async def step(service: Any, lst: Any) -> None:
        if app_state.ui_preferences_store is None or not settings().get("panel") or not panel_kind.approved(lst, service.store.own_iid):
            return
        done = await asyncio.to_thread(work, service, lst)
        if done is not None:
            await panel_apply.announce(app_state, *done)

    return step
