
from src.core.agent_family_display import resolve_family_for_display
from src.config import wrapper_reader
from src.models import SessionRecord
from typing import Optional





def _family_name_for_row(row: dict) -> Optional[str]:
    stored = row.get("agent_family")
    if stored:
        return str(stored)
    agent_type = row.get("agent_type")
    if not agent_type:
        return None
    wrappers = wrapper_reader.configured_wrappers()
    family, _source = resolve_family_for_display(str(agent_type), wrappers)
    return family.name if family else None


def attach_host_labels(conn, rows: list) -> None:
    keys = sorted({r.get("host_key") for r in rows} - {None, "local"})
    if not keys:
        return
    marks = ",".join("?" * len(keys))
    labels = dict(conn.execute(f"SELECT key, label FROM hosts WHERE key IN ({marks})", keys).fetchall())
    for row in rows:
        row["host_label"] = labels.get(row.get("host_key"))


def _session_record_payload(row: dict, unread_store=None, theme_store=None) -> SessionRecord:
    from src.core.session_sleep import is_asleep, is_closed
    from src.core.session_store import is_owned_origin
    from src.core.unread_follow_up import asleep_flag

    asleep = is_asleep(row)

    return SessionRecord(
        session_uuid=str(row.get("session_uuid")),
        origin=str(row.get("origin")),
        owned=is_owned_origin(row.get("origin")),
        adopted_at=row.get("adopted_at"),
        tmux_socket=row.get("tmux_socket"),
        tmux_name=row.get("tmux_name"),
        tmux_created_epoch=row.get("tmux_created_epoch"),
        lifecycle=str(row.get("lifecycle")),
        lifecycle_checked_at=row.get("lifecycle_checked_at"),
        lifecycle_source=row.get("lifecycle_source"),
        project_id=row.get("project_id"),
        project_name=row.get("project_name"),
        project_attribution=str(row.get("project_attribution")),
        working_dir=row.get("working_dir"),
        agent_type=row.get("agent_type"),
        agent_family=_family_name_for_row(row),
        agent_family_source=row.get("agent_family_source"),
        model=row.get("model"),
        archived_at=row.get("archived_at"),
        title=row.get("title"),
        id=row.get("id"),
        parent_session_id=row.get("parent_session_id"),
        fork_kind=row.get("fork_kind"),
        created_at=row.get("created_at"),
        last_seen_running_at=row.get("last_seen_running_at"),
        last_work_at=row.get("last_work_at"),
        notifications_muted=bool(row.get("notifications_muted")),
        notification_policy_generation=int(
            row.get("notification_policy_generation") or 0
        ),
        asleep=asleep,
        host_key=row.get("host_key"),
        host_label=row.get("host_label"),
        closed=is_closed(row),
        unread=asleep_flag(unread_store, row) if asleep else None,
        pinned_theme=(
            theme_store.resolve_project_theme(row.get("working_dir"), row.get("tmux_name"))
            if asleep and theme_store is not None else None
        ),
    )
