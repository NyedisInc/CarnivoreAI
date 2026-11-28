
import { claimsOf, liveRowIs, rowNameFor } from './record-row-name';

interface ClosedRecord {
    closed?: boolean;
    session_uuid?: string;
    tmux_name?: string | null;
    title?: string | null;
    last_work_at?: string | null;
    owned?: boolean;
    tmux_created_epoch?: number;
    agent_family?: string | null;
    agent_family_source?: string | null;
    agent_wrapper_icon?: string | null;
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

export function addClosedRows(
    rows: Array<Record<string, unknown>>, records: readonly unknown[], keep?: (row: Record<string, unknown>) => boolean,
): number {
    const claims = claimsOf(rows || []);
    const seen = new Set<string>();
    let added = 0;
    for (const raw of Array.isArray(records) ? records : []) {
        const rec = raw as ClosedRecord | null;
        if (!rec || rec.closed !== true || !rec.session_uuid || seen.has(rec.session_uuid)) continue;
        if (liveRowIs(claims, rec.session_uuid, rec.tmux_name)) continue;
        const row: Record<string, unknown> = {
            name: rowNameFor(claims, CLOSED_NAME_PREFIX, rec.session_uuid, rec.tmux_name),
            label: rec.title != null ? rec.title : null,
            closed: true,
            asleep: false,
            archived: false,
            status: CLOSED_STATUS,
            session_uuid: rec.session_uuid,
            tmux_name: rec.tmux_name || null,
            last_work_at: rec.last_work_at || null,
            session_id: null,
            is_active: false,
            unread: false,
            created_by_cloude: typeof rec.owned === 'boolean' ? rec.owned : null,
            created_at_epoch: Number(rec.tmux_created_epoch) || 0,
            agent_family: rec.agent_family != null ? rec.agent_family : null,
            agent_family_source: rec.agent_family_source != null ? rec.agent_family_source : null,
            agent_wrapper_icon: rec.agent_wrapper_icon != null ? rec.agent_wrapper_icon : null,
            project_id: rec.project_id != null ? rec.project_id : null,
            project_name: rec.project_name != null ? rec.project_name : null,
            working_dir: rec.working_dir != null ? rec.working_dir : null,
            notifications_muted: !!rec.notifications_muted,
            pinned_theme: rec.pinned_theme || null,
        };
        if (keep && !keep(row)) continue;
        seen.add(rec.session_uuid);
        rows.push(row);
        added += 1;
    }
    return added;
}
