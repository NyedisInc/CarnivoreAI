
from __future__ import annotations

from typing import Any, Dict, Mapping, NamedTuple


class Merge(NamedTuple):

    into: str
    preset: Mapping[str, Any]
    note: str


MERGED: Dict[str, Merge] = {
    "sessions_roster": Merge("agents_lookup", {"view": "roster"},
                             "OLD NAME of agents_lookup with view roster, kept so existing callers still work: "
                             "who is on this computer, with each session's descriptions and family."),
    "pack_machines_list": Merge("computers_list", {"detail": "specs"},
                                "OLD NAME of computers_list with detail specs, kept so existing callers still work: "
                                "every Pack computer's specs, live load and the master."),
    "cplugs_list": Merge("plugins_list", {}, "OLD NAME of plugins_list, kept so existing callers still work: "
                                              "every plugin, its state, what it asks and what is granted."),
}


def into(name: Any) -> Any:
    return MERGED[name].into if isinstance(name, str) and name in MERGED else name


def with_preset(name: Any, args: Any) -> Dict[str, Any]:
    given = dict(args) if isinstance(args, dict) else {}
    merge = MERGED.get(name) if isinstance(name, str) else None
    return {**merge.preset, **given} if merge else given
