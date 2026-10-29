"""Can each offered session be reopened RIGHT NOW, and how? SYNCHRONOUS.

  REFUSALS, EACH ONE A MEASURED FACT:
    already_running_elsewhere   a live claude process, in tmux or not, has
                                this conversation open (Claude Code's own
                                pid registry, validated against ``ps``).
    unidentified_claude_here    a claude runs in this folder and its
                                conversation could not be identified.
    writers_unmeasured          ``ps`` did not run, so no process can be
                                ruled out. Not having looked is not a yes.
    no_conversation             a CLAUDE row names no conversation; reopening
                                it would be a fresh start, not a reopen. A
                                SHELL row never has one and is not blocked.
    transcript_missing          the conversation's file was looked for under
                                every spelling of the folder and is absent.
    name_in_use                 another tmux instance holds the row's name.
    no_wrapper                  no configured wrapper can be chosen.
    presence_unmeasured         the listing did not run or was incomplete.
"""

from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

import structlog

from src.core import conversation_writers as cw
from src.core.session_journal_measure import Measurement
from src.core.claude_folder_trust import TRUST_UNKNOWN, folder_trust, load_trust_map
from src.core.session_restore_offer import NEVER_OFFERED
from src.core.agent_families import get_family
from src.core.session_agent_infer import strip_per_run_flags
from src.core.session_restore_rules import choose_wrapper, missing_flags, pick_conversation

logger = structlog.get_logger()

SHELL_FAMILY: str = "shell"
KIND_GONE: str = "gone"
KIND_HUSK: str = "husk"

BLOCK_ELSEWHERE: str = "already_running_elsewhere"
BLOCK_UNIDENTIFIED: str = "unidentified_claude_here"
BLOCK_WRITERS_UNMEASURED: str = "writers_unmeasured"
BLOCK_NO_CONVERSATION: str = "no_conversation"
BLOCK_TRANSCRIPT_MISSING: str = "transcript_missing"
BLOCK_NAME_IN_USE: str = "name_in_use"
BLOCK_NO_WRAPPER: str = "no_wrapper"
BLOCK_PRESENCE_UNMEASURED: str = "presence_unmeasured"
BLOCK_ROW_MISSING: str = "row_missing"

WRAPPER_FROM_SHELL_FAMILY: str = "shell_family_default"

_WRITER_TO_BLOCK = {
    cw.CONFLICT_LIVE_WRITER: BLOCK_ELSEWHERE,
    cw.CONFLICT_SAME_DIR_UNIDENTIFIED: BLOCK_UNIDENTIFIED,
}


def wrapper_table() -> Tuple[Dict[str, FrozenSet[str]], Optional[str], List[Dict[str, str]]]:
    from src.core.session_agent_infer import _is_claude_family, wrapper_flag_signature
    from src.core.session_manager import _configured_wrappers

    sigs: Dict[str, FrozenSet[str]] = {}
    options: List[Dict[str, str]] = []
    default_id: Optional[str] = None
    for w in _configured_wrappers():
        wid = getattr(w, "id", None)
        if not wid or not _is_claude_family(w):
            continue
        sigs[wid] = frozenset(wrapper_flag_signature(w))
        options.append({"id": wid, "label": getattr(w, "label", None) or wid})
        if getattr(w, "default", False) and default_id is None:
            default_id = wid
    return sigs, default_id, options


def _is_shell_row(row: Mapping[str, Any]) -> bool:
    return str(row.get("agent_family") or "").strip().lower() == SHELL_FAMILY


def _kind_and_block(row: Mapping[str, Any], m: Measurement) -> Tuple[Optional[str], Optional[str], str]:
    from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, tmux_presence
    from src.core.tmux_backend import SESSION_PREFIX

    if not m.listing_ok:
        return KIND_GONE, BLOCK_PRESENCE_UNMEASURED, "the tmux listing did not run"
    name, epoch = row.get("tmux_name"), row.get("tmux_created_epoch")
    same = [p for p in m.panes if p.name == name and p.epoch == epoch]
    if same:
        if not same[0].dead:
            return None, None, "running"
        return KIND_HUSK, None, "its pane is still on the socket with the process exited"
    presence = tmux_presence(
        name, listing_ok=m.listing_ok, listing_complete=m.listing_complete,
        names=[p.name for p in m.panes], namespace_prefix=SESSION_PREFIX,
    )
    if presence.outcome == TMUX_GONE:
        return KIND_GONE, None, "its tmux session is gone"
    if presence.outcome == TMUX_PRESENT:
        return KIND_GONE, BLOCK_NAME_IN_USE, f"another session is using the name {name}"
    return KIND_GONE, BLOCK_PRESENCE_UNMEASURED, presence.detail


def evaluate_candidate(
    candidate: Mapping[str, Any],
    row: Optional[Mapping[str, Any]],
    m: Measurement,
    wrappers: Tuple[Dict[str, FrozenSet[str]], Optional[str], List[Dict[str, str]]],
    *,
    trust_map: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    from src.core.session_imported_restart import resume_directory

    sigs, default_id, options = wrappers
    base = {
        "session_uuid": candidate.get("session_uuid"),
        "instance": candidate.get("instance"),
        "title": (row or {}).get("title") or candidate.get("title"),
        "tmux_name": (row or {}).get("tmux_name") or candidate.get("tmux_name"),
        "group": candidate.get("group"),
        "last_seen_live": candidate.get("last_seen_live"),
        "last_work_at": (row or {}).get("last_work_at") or candidate.get("last_work_at"),
        "source": candidate.get("source"),
        "lost_reason": candidate.get("reason"),
        "wrapper_options": options,
    }
    if row is None:
        return {**base, "kind": KIND_GONE, "selectable": False, "blocked": BLOCK_ROW_MISSING,
                "detail": "the session's record could not be read"}
    kind, block, where = _kind_and_block(row, m)
    if kind is None:
        return None
    recorded = row.get("claude_session_uuid")
    measured = candidate.get("conversation_measured")
    if kind == KIND_HUSK:
        conversation, conv_source, agree = recorded, "recorded", (measured in (None, recorded))
    else:
        conversation, conv_source, agree = pick_conversation(measured, recorded)
    raw_flags = candidate.get("observed_flags")
    observed = strip_per_run_flags(raw_flags) if raw_flags is not None else None
    shell = _is_shell_row(row)
    if shell:
        shell_wrapper = get_family(SHELL_FAMILY).default_wrapper_id
        chosen, wsource, wdetail = (
            shell_wrapper, WRAPPER_FROM_SHELL_FAMILY,
            "a plain shell comes back as a fresh shell in its folder",
        )
        options = [*options, {"id": shell_wrapper, "label": SHELL_FAMILY}]
        base["wrapper_options"] = options
    else:
        chosen, wsource, wdetail = choose_wrapper(row.get("agent_type"), observed, sigs, default_id)
    folder = candidate.get("folder") or row.get("working_dir")
    out = {
        **base, "kind": kind, "where": where,
        "conversation": conversation, "conversation_source": conv_source,
        "conversation_recorded": recorded, "conversation_measured": measured,
        "conversation_agree": agree,
        "folder": folder, "observed_flags": sorted(observed) if observed is not None else None,
        "wrapper_default": chosen, "wrapper_source": wsource, "wrapper_detail": wdetail,
        "wrapper_drops": {
            o["id"]: [] if shell else sorted(missing_flags(observed, sigs.get(o["id"])))
            for o in options
        },
    }
    if block is None and not conversation and not shell:
        block, where = BLOCK_NO_CONVERSATION, "no conversation is recorded for this session"
    if block is None and kind == KIND_GONE and not shell:
        directory = resume_directory(folder, conversation, family=row.get("agent_family"))
        if directory.refuses:
            block, where = BLOCK_TRANSCRIPT_MISSING, directory.detail or "the conversation file is missing"
        elif directory.working_dir:
            out["folder"] = folder = directory.working_dir
    if block is None and not shell and not m.writers_ok:
        block, where = BLOCK_WRITERS_UNMEASURED, "running claude processes could not be listed"
    if block is None and not shell:
        conflict = cw.writer_conflict(conversation, os.path.realpath(folder) if folder else None, m.writers)
        if conflict:
            block, where = _WRITER_TO_BLOCK.get(conflict[0], BLOCK_ELSEWHERE), conflict[1]
    if block is None and not chosen:
        block, where = BLOCK_NO_WRAPPER, wdetail
    out.update({"selectable": block is None, "blocked": block, "detail": where,
                "folder_trust": folder_trust(out.get("folder"), trust_map) if trust_map is not None
                else TRUST_UNKNOWN})
    return out


def evaluate_offer(offer: Mapping[str, Any], m: Measurement) -> List[Dict[str, Any]]:
    rows = {r.get("session_uuid"): r for r in m.rows} if m.rows_ok else {}
    wrappers = wrapper_table()
    trust_map = load_trust_map()
    out = []
    for c in offer.get("candidates") or []:
        row = rows.get(c.get("session_uuid"))
        if row is not None and row.get("lifecycle_source") in NEVER_OFFERED:
            continue
        item = evaluate_candidate(c, row, m, wrappers,
                                  trust_map=trust_map)
        if item is not None and item.get("kind") != KIND_HUSK:
            out.append(item)
    out.sort(key=lambda i: 0 if i.get("selectable") else 1)
    return out
