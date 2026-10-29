/* not asleep */

interface ClosedRecord {
    closed?: boolean;
    session_uuid?: string;
    tmux_name?: string | null;
    title?: string | null;
    owned?: boolean;
    tmux_created_epoch?: number;
    agent_family?: string | null;
    agent_family_source?: string | null;
    project_id?: number | null;
    project_name?: string | null;
    working_dir?: string | null;
    notifications_muted?: boolean;
    pinned_theme?: string | null;
}

export const CLOSED_NAME_PREFIX = 'closed:';

export const CLOSED_STATUS = 'closed';

export function isClosedRow(row: Record<string, unknown> | null | undefined): boolean {
    return !!row && row.closed === true;
}

export function addClosedRows(rows: Array<Record<string, unknown>>, records: readonly unknown[]): number {
    const taken = new Set((rows || []).map((r) => r && r.name));
    const seen = new Set<string>();
    let added = 0;
    for (const raw of Array.isArray(records) ? records : []) {
        const rec = raw as ClosedRecord | null;
        if (!rec || rec.closed !== true || !rec.session_uuid || seen.has(rec.session_uuid)) continue;
        const name = rec.tmux_name || `${CLOSED_NAME_PREFIX}${rec.session_uuid}`;
        if (taken.has(name)) continue;
        taken.add(name);
        seen.add(rec.session_uuid);
        rows.push({
            name,
            label: rec.title != null ? rec.title : null,
            closed: true,
            asleep: false,
            archived: false,
            status: CLOSED_STATUS,
            session_uuid: rec.session_uuid,
            session_id: null,
            is_active: false,
            unread: false,
            created_by_cloude: typeof rec.owned === 'boolean' ? rec.owned : null,
            created_at_epoch: Number(rec.tmux_created_epoch) || 0,
            agent_family: rec.agent_family != null ? rec.agent_family : null,
            agent_family_source: rec.agent_family_source != null ? rec.agent_family_source : null,
            project_id: rec.project_id != null ? rec.project_id : null,
            project_name: rec.project_name != null ? rec.project_name : null,
            working_dir: rec.working_dir != null ? rec.working_dir : null,
            notifications_muted: !!rec.notifications_muted,
            pinned_theme: rec.pinned_theme || null,
        });
        added += 1;
    }
    return added;
}
