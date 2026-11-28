
from __future__ import annotations

import posixpath
from typing import Any, Dict, Iterable, Mapping, Optional, Set, Tuple

LOCAL_HOST = "local"

PEER_SCHEME = "peer://"


def _clean_root(root: Any) -> Optional[str]:
    if not isinstance(root, str) or not root.startswith("/"):
        return None
    return posixpath.normpath(root)


def _split_root(root: Any) -> Optional[Tuple[str, str]]:
    if not isinstance(root, str):
        return None
    if root.startswith("/"):
        return ("", posixpath.normpath(root))
    if root.startswith(PEER_SCHEME):
        rest = root[len(PEER_SCHEME):]
        peer_host, slash, tail = rest.partition("/")
        if not slash or not peer_host or not tail:
            return None
        return (f"{PEER_SCHEME}{peer_host}", posixpath.normpath("/" + tail))
    return None


def _is_peer_root(root: Any) -> bool:
    return isinstance(root, str) and root.startswith(PEER_SCHEME)


def _break_cycles(out: Dict[int, Optional[int]], fallback: Mapping[int, Optional[int]], explicit: Set[int]) -> None:
    for _pass in range(2):
        state: Dict[int, int] = {}
        broke = False
        for start in sorted(out):
            if state.get(start, 0) != 0:
                continue
            path = []
            index: Dict[int, int] = {}
            cur: Optional[int] = start
            while cur is not None and cur in out:
                st = state.get(cur, 0)
                if st == 2:
                    break
                if st == 1:
                    cycle = path[index[cur]:]
                    reverted = [n for n in cycle if n in explicit]
                    if reverted:
                        for node in reverted:
                            out[node] = fallback.get(node)
                            explicit.discard(node)
                    else:
                        for node in cycle:
                            out[node] = None
                    broke = True
                    break
                state[cur] = 1
                index[cur] = len(path)
                path.append(cur)
                cur = out.get(cur)
            for node in path:
                state[node] = 2
        if not broke:
            return


def parent_project_ids(
    projects: Iterable[Dict[str, Any]],
    folder_parents: Optional[Mapping[str, str]] = None,
    uid_parents: Optional[Mapping[str, str]] = None,
) -> Dict[int, Optional[int]]:
    rows = [p for p in projects if isinstance(p.get("id"), int) and not isinstance(p.get("id"), bool)]
    holders: Dict[Tuple[str, str, str], int] = {}
    live_by_uid: Dict[str, int] = {}
    for p in rows:
        if p.get("archived_at"):
            continue
        pid = p["id"]
        uid = p.get("uid")
        if isinstance(uid, str) and uid:
            live_by_uid[uid] = min(live_by_uid.get(uid, pid), pid)
        parsed = _split_root(p.get("root"))
        if parsed is None:
            continue
        scope, clean = parsed
        key = (p.get("host_key") or LOCAL_HOST, scope, clean)
        holders[key] = min(holders.get(key, pid), pid)

    path_out: Dict[int, Optional[int]] = {}
    for p in rows:
        pid = p["id"]
        host = p.get("host_key") or LOCAL_HOST
        parsed = _split_root(p.get("root"))
        parent: Optional[int] = None
        if parsed is not None:
            scope, clean = parsed
            linked = _clean_root((folder_parents or {}).get(clean)) if scope == "" and host == LOCAL_HOST else None
            if linked is not None and holders.get((host, "", linked)) not in (None, pid):
                path_out[pid] = holders[(host, "", linked)]
                continue
            current = clean
            while current != "/":
                current = posixpath.dirname(current)
                found = holders.get((host, scope, current))
                if found is not None and found != pid:
                    parent = found
                    break
        path_out[pid] = parent

    out = dict(path_out)
    explicit: Set[int] = set()
    for p in rows:
        pid = p["id"]
        raw_parent_uid = p.get("parent_project_uid")
        if not (isinstance(raw_parent_uid, str) and raw_parent_uid):
            uid = p.get("uid")
            if uid_parents and _is_peer_root(p.get("root")) and isinstance(uid, str) and uid:
                raw_parent_uid = uid_parents.get(uid)
            else:
                raw_parent_uid = None
        if isinstance(raw_parent_uid, str) and raw_parent_uid:
            candidate = live_by_uid.get(raw_parent_uid)
            if candidate is not None and candidate != pid:
                out[pid] = candidate
                explicit.add(pid)

    if explicit:
        _break_cycles(out, path_out, explicit)
    return out
