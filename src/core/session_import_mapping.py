
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from src.core.project_attribution import attribute


def attribute_working_dir(
    working_dir: Optional[str], roots: Dict[str, int]
) -> tuple[Optional[int], str]:
    """Resolve one session's working directory to a project, deepest match wins.

    Description: design section 5.3 step 7. THE RULE ITSELF NOW LIVES IN
      src/core/project_attribution.py and this is a thin delegate, kept
      because the import is not the only caller any more - the adopt path
      asks the same question - and a rule with two callers must not have
      two copies. See that module for why ``resolve()`` is forbidden and
      why ``none`` and ``unknown`` are different answers.

      What changed underneath, and it is the whole of the live-data bug:
      the old body compared RAW strings, so a ``~``-form path could never
      match an expanded root, and it ranked the deepest match by string
      LENGTH rather than by path depth.
    Inputs: working_dir (str | None) - the probed cwd; None means the
      probe did not answer. roots (dict[str, int]) - project root ->
      project id.
    Output: tuple[int | None, str] - (project_id, attribution), where
      attribution is one of ``derived_deepest``, ``none``, ``unknown``.
    Example: attribute_working_dir('/a/b/c', {'/a/b': 7})  # (7, 'derived_deepest')
    """
    return attribute(working_dir, roots)


def _project_roots(conn: sqlite3.Connection) -> Dict[str, int]:
    try:
        rows = conn.execute("SELECT root, id FROM projects").fetchall()
    except sqlite3.Error:
        return {}
    return {str(row[0]): int(row[1]) for row in rows}


def _row_fields(row: Any) -> Dict[str, Any]:
    if isinstance(row, str):
        return {"name": row, "tmux_created_epoch": 0}
    if isinstance(row, dict):
        name = row.get("name")
        epoch = row.get("created_at_epoch", row.get("tmux_created_epoch", 0))
        try:
            epoch_int = int(epoch)
        except (TypeError, ValueError):
            epoch_int = 0
        return {
            "name": name,
            "tmux_created_epoch": epoch_int,
            "working_dir": row.get("working_dir"),
            "tmux_session_id": row.get("tmux_session_id"),
        }
    return {"name": None, "tmux_created_epoch": 0}


def _merge_fields(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not entry:
        return {}
    mapping = {
        "agent_type": entry.get("agent_type"),
        "model": entry.get("model"),
        "pinned_theme": entry.get("pinned_theme"),
        "legacy_session_id": entry.get("id") or entry.get("session_id"),
        "title": entry.get("title"),
        "unread_auto": entry.get("unread_auto"),
        "unread_manual": entry.get("unread_manual"),
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _persisted_session_id(entry: Dict[str, Any]) -> Optional[str]:
    value = entry.get("tmux_session_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stopped_epoch(entry: Dict[str, Any]) -> Optional[int]:
    """Choose the instance epoch for a persisted session with no live row.

    Description: the entry's own recorded creation epoch when it has one,
      and ``None`` - meaning NOT RECORDED - when it does not.

      THIS USED TO RETURN 0, AND THAT 0 WAS A MEASUREMENT NOBODY MADE.
      The persisted ``session_metadata.json`` an upgrading install
      carries has no epoch field at all, so the fallback was the normal
      path, not the exotic one. A synthesized 0 is indistinguishable
      downstream from an epoch tmux actually reported, and it entered the
      IDENTITY KEY: with ``origin='created'`` the row landed in
      :func:`src.core.session_store.owned_instances`, which gave the
      ownership resolver a specific, epoch-keyed opinion about that name.
      The resolver's tier 2 then issued a CONFIDENT NEGATIVE against it,
      so the user's next real session of the same name badged
      ``owned=False`` - permanently, since nothing ever deletes a
      sessions row. An invented value driving a confident verdict is
      exactly what the three-outcome rule forbids, and the identity
      layer is the worst place to do it.

      ``None`` is the representation this design already had for "epoch
      unknown" and the schema was already built for it: the unique index
      ``ux_sessions_host_instance`` (the triple's, before v40) is PARTIAL
      (``WHERE ... tmux_created_epoch IS NOT NULL``) and
      ``owned_instances`` filters ``tmux_created_epoch IS NOT NULL``. So
      a NULL-epoch row cannot collide with a real instance and cannot
      reach the ownership resolver at all - it is recorded, visible, and
      silent on the question it has no evidence about.

      The cost, stated plainly: two persisted entries for the same name
      with no epoch produce two rows rather than one, because SQLite
      treats NULLs as distinct in a unique index. That is the correct
      trade. Duplicate history is a cosmetic defect; a fabricated
      identity that silently disowns a live session is not.
    Inputs: entry (dict) - one persisted session record.
    Output: int | None - the recorded epoch, or None when the entry
      carries none or carries one that will not parse as an integer.
    Example:
        >>> _stopped_epoch({"tmux_created_epoch": 1755000000})
        1755000000
        >>> _stopped_epoch({}) is None
        True
    """
    for key in ("tmux_created_epoch", "created_at_epoch"):
        value = entry.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None
