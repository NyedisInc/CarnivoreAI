
export const ARCHIVED_NAME_PREFIX = 'archived:';

export const ARCHIVED_STATUS = 'archived';

interface ArchivedRecord {
    archived_at?: unknown;
    session_uuid?: string;
    tmux_name?: string | null;
    title?: string | null;
    project_id?: number | null;
    project_name?: string | null;
    working_dir?: string | null;
    agent_family?: string | null;
    agent_family_source?: string | null;
    owned?: boolean;
    tmux_created_epoch?: number;
    last_work_at?: string | null;
    notifications_muted?: boolean;
    pinned_theme?: string | null;
}

export function archivedRows(
    records: readonly unknown[],
    shown: boolean,
    taken: ReadonlySet<string>,
): Array<Record<string, unknown> & { name: string }> {
    if (!shown || !Array.isArray(records)) return [];
    const seen = new Set<string>();
    const out: Array<Record<string, unknown> & { name: string }> = [];
    for (const raw of records) {
        const rec = raw as ArchivedRecord | null;
        if (!rec || !rec.archived_at || !rec.session_uuid || seen.has(rec.session_uuid)) continue;
        if (rec.tmux_name && taken.has(rec.tmux_name)) continue;
        seen.add(rec.session_uuid);
        out.push({
            name: `${ARCHIVED_NAME_PREFIX}${rec.session_uuid}`,
            label: rec.title != null ? rec.title : null,
            asleep: false,
            archived: true,
            status: ARCHIVED_STATUS,
            session_uuid: rec.session_uuid,
            session_id: null,
            is_active: false,
            is_this_tab: false,
            unread: false,
            created_by_cloude: typeof rec.owned === 'boolean' ? rec.owned : null,
            created_at_epoch: Number(rec.tmux_created_epoch) || 0,
            last_work_at: rec.last_work_at || null,
            agent_family: rec.agent_family != null ? rec.agent_family : null,
            agent_family_source: rec.agent_family_source != null ? rec.agent_family_source : null,
            project_id: rec.project_id != null ? rec.project_id : null,
            project_name: rec.project_name != null ? rec.project_name : null,
            working_dir: rec.working_dir != null ? rec.working_dir : null,
            notifications_muted: !!rec.notifications_muted,
            pinned_theme: rec.pinned_theme || null,
            running_model: null,
            running_model_effort: null,
            running_model_tier: null,
            running_context_used_pct: null,
        });
    }
    return out;
}

export function isArchivedRow(row: Record<string, unknown> | null | undefined): boolean {
    return !!row && row.archived === true;
}

export function archivedLast<T extends Record<string, unknown>>(rows: T[]): T[] {
    if (!rows.some((r) => isArchivedRow(r))) return rows;
    return [...rows.filter((r) => !isArchivedRow(r)), ...rows.filter((r) => isArchivedRow(r))];
}
