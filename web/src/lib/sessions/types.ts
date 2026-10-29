
import type { UsageLimit } from '../../opscenter/api/types';

export interface ScheduledMark {
    name: string;
    enabled: boolean;
    next_fire_at: number | null;
}

export interface SessionCore {
    id?: string | null;
    pty_pid?: number | null;
    working_dir?: string | null;
    status?: string | null;
    created_at?: string | null;
    last_activity?: string | null;
    agent_type?: string | null;
    pinned_theme?: string | null;
    tmux_session?: string | null;
    model?: string | null;
}

export interface SessionListItem {
    session?: SessionCore | null;
    task_lead?: boolean | null;
    do_not_disturb?: boolean | null;
    activity_status?: string | null;
    unread?: boolean | null;
    startup_gate?: string | null;
    status_source?: string | null;
    usage_limit?: UsageLimit | null;
    automation?: { automation_id: string; run_id: string; name: string } | null;
    messaging?: { directions: string[]; held: number } | null;
    /* there is nothing */
    activity_hint?: string | null;
    parked_summary?: string | null;
    host_key?: string | null;
    host_label?: string | null;
    host_state?: string | null;
    tmux_session?: string | null;
    spectator_expires_at?: string | null;
    subagents_state?: string | null;
    subagents_running?: number | null;
    subagents_total?: number | null;
    workflow_active?: boolean | null;
    timers_state?: string | null;
    timers_live?: number | null;
    timers_next_fire_at?: string | null;
    background_open?: number | null;
    automations_state?: string | null;
    automations_total?: number | null;
    automations_enabled?: number | null;
    automations_next?: ScheduledMark[] | null;
    agent_type?: string | null;
    agent_family?: string | null;
    agent_family_source?: string | null;
    agent_wrapper_label?: string | null;
    agent_wrapper_icon?: string | null;
    launched_with?: LaunchedWith | null;
    pinned_theme?: string | null;
    session_backend?: string | null;
    session_row_id?: number | null;
    parent_session_id?: string | null;
    label?: string | null;
    created_by_cloude?: boolean | null;
    created_by_us?: boolean | null;
    created_at_epoch?: number | null;
    id?: string | null;
}

export interface AttachableSession {
    name: string;
    label?: string | null;
    created_by_cloude?: boolean | null;
    created_by_us?: boolean | null;
    created_at_epoch?: number | null;
    window_count?: number | null;
    agent_type?: string | null;
    agent_family?: string | null;
    agent_family_source?: string | null;
    agent_wrapper_label?: string | null;
    agent_wrapper_icon?: string | null;
    launched_with?: LaunchedWith | null;
    pinned_theme?: string | null;
    session_row_id?: number | null;
    parent_session_id?: string | null;
    status?: string | null;
    unread?: boolean | null;
    listing_ok?: boolean | null;
    listing_reason?: string | null;
}

export interface RunningSessionRow extends AttachableSession {
    is_active?: boolean;
    session_id?: string | null;
    startup_gate?: string | null;
    status_source?: string | null;
    activity_hint?: string | null;
    parked_summary?: string | null;
    usage_limit?: UsageLimit | null;
    host_key?: string | null;
    host_label?: string | null;
    host_state?: string | null;
}

export interface SessionRecord {
    session_uuid?: string | null;
    id?: number | null;
    tmux_name?: string | null;
    tmux_created_epoch?: number | null;
    lifecycle?: string | null;
    project_id?: number | null;
    project_attribution?: string | null;
    working_dir?: string | null;
    archived_at?: string | null;
    title?: string | null;
    parent_session_id?: string | null;
    last_work_at?: string | null;
    owned?: boolean | null;
    agent_type?: string | null;
    agent_family?: string | null;
    agent_family_source?: string | null;
}

export interface ListingState {
    ok: boolean;
    reason: string | null;
    detail: string | null;
    sources: string[];
}

export interface ProjectAuthority {
    mode?: string | null;
    degraded?: boolean | null;
    writable?: boolean | null;
    message?: string | null;
}

export interface ProjectPresenceRow {
    raw_path?: string | null;
    root?: string | null;
    [key: string]: unknown;
}

export interface ProjectPresencePayload {
    status?: string | null;
    projects?: ProjectPresenceRow[] | null;
}

export interface LaunchedWith {
    profile: string;
    label: string;
    harness?: string | null;
    account?: string | null;
    model?: string | null;
    permissions?: string | null;
}

export interface ProjectRow {
    name?: string | null;
    path?: string | null;
    root?: string | null;
    [key: string]: unknown;
}

export type Translate = (key: string, params?: Record<string, unknown> | null) => string;
