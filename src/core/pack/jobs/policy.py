
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from src.core.pack.errors.input_error import PackInputError
from src.core.pack.jobs.store import JobStore


@dataclass
class Policy:

    project_uid: str
    auto_delegate: bool = False
    never_use: List[str] = field(default_factory=list)
    carry: List[str] = field(default_factory=list)
    bring_back: List[str] = field(default_factory=list)
    setup: Optional[List[str]] = None
    local_only: List[str] = field(default_factory=list)


def _list(raw: Optional[str]) -> List[str]:
    return [str(x) for x in json.loads(raw)] if raw else []


def get(store: JobStore, uid: str) -> Policy:
    row = store.policy_row(uid)
    if row is None:
        return Policy(project_uid=uid)
    return Policy(project_uid=uid, auto_delegate=bool(row["auto_delegate"]), never_use=_list(row["never_use_json"]),
                  carry=_list(row["carry_json"]), bring_back=_list(row["bring_back_json"]),
                  setup=_list(row["setup_json"]) if row["setup_json"] else None,
                  local_only=_list(row.get("local_only_json")))


def set_auto(store: JobStore, uid: str, on: bool) -> None:
    store.policy_upsert(uid, auto_delegate=1 if on else 0)


def _check(items: List[str]) -> List[str]:
    if not all(isinstance(i, str) and i for i in items):
        raise PackInputError("every entry must be a non-empty string")
    return list(items)


def _check_wire(never_use: Optional[List[str]], carry: Optional[List[str]], bring_back: Optional[List[str]],
                setup: Optional[List[str]]) -> None:
    for items in (carry, bring_back):
        for item in items or []:
            if item.startswith("/") or ".." in item.split("/") or "\0" in item:
                raise PackInputError("carry and bring back entries are relative paths with no ..")
    if bring_back is not None and len(bring_back) > 100:
        raise PackInputError("at most 100 bring back entries")
    if setup is not None and (len(setup) > 10 or any(len(s) > 2000 or "\0" in s for s in setup)):
        raise PackInputError("at most 10 setup steps of at most 2000 characters")


def set_lists(store: JobStore, uid: str, *, never_use: Optional[List[str]] = None, carry: Optional[List[str]] = None,
              bring_back: Optional[List[str]] = None, setup: Optional[List[str]] = None,
              local_only: Optional[List[str]] = None) -> None:
    _check_wire(never_use, carry, bring_back, setup)
    if local_only is not None and (len(local_only) > 50 or any(len(s) > 200 or "\0" in s for s in local_only)):
        raise PackInputError("at most 50 local_only patterns of at most 200 characters")
    cols = {}
    for name, value in (("never_use_json", never_use), ("carry_json", carry), ("bring_back_json", bring_back),
                        ("local_only_json", local_only)):
        if value is not None:
            cols[name] = json.dumps(_check(value))
    if setup is not None:
        cols["setup_json"] = json.dumps(_check(setup)) if setup else None
    if cols:
        store.policy_upsert(uid, **cols)


def record_auto_replica(store: JobStore, uid: str, install_id: str) -> None:
    store.auto_replica_add(uid, install_id)


def forget_auto_replica(store: JobStore, project_uid: str, install_id: str) -> None:
    store.auto_replica_delete(project_uid, install_id)


def auto_replicas(store: JobStore, uid: str) -> List[str]:
    return store.auto_replica_list(uid)


def record_detached_root(store: JobStore, uid: str, install_id: str, root: str) -> None:
    store.detached_set(uid, install_id, root)


def detached_root(store: JobStore, uid: str, install_id: str) -> Optional[str]:
    return store.detached_get(uid, install_id)


def forget_detached_root(store: JobStore, uid: str, install_id: str) -> None:
    store.detached_delete(uid, install_id)

