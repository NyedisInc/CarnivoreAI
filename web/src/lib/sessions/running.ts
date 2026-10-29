/* could not */
import type {
    AttachableSession,
    ListingState,
    RunningSessionRow,
    SessionListItem,
    Translate,
} from './types';
import { emptyListing, noteListingUnknown } from './listing';

function createdByUs(row: { created_by_us?: boolean | null; created_by_cloude?: boolean | null }): boolean {
    if (typeof row.created_by_us === 'boolean') return row.created_by_us;
    return !!row.created_by_cloude;
}

export function mergeLiveSession(rows: RunningSessionRow[], live: SessionListItem): boolean {
    const tmuxName = live && live.tmux_session;
    if (!tmuxName) return false;
    const liveStatus = (live && live.activity_status) || 'unknown';
    const liveUnread = !!(live && live.unread);
    const liveId = (live.session && live.session.id) || live.id || null;
    const existing = rows.find((s) => s.name === tmuxName);
    if (existing) {
        existing.is_active = true;
        existing.session_id = liveId || existing.session_id;
        existing.status = liveStatus;
        existing.unread = liveUnread;
        existing.created_by_cloude = createdByUs(live);
        existing.startup_gate = live.startup_gate;
        existing.status_source = live.status_source;
        existing.activity_hint =
            live.activity_hint !== undefined ? live.activity_hint : null;
        existing.parked_summary =
            live.parked_summary !== undefined ? live.parked_summary : null;
        existing.usage_limit = live.usage_limit ?? null;
        existing.host_key = live.host_key ?? null;
        existing.host_label = live.host_label ?? null;
        existing.host_state = live.host_state ?? null;
        existing.agent_family = live.agent_family !== undefined ? live.agent_family : null;
        existing.agent_family_source = live.agent_family_source !== undefined
            ? live.agent_family_source : null;
        existing.agent_wrapper_label = live.agent_wrapper_label !== undefined
            ? live.agent_wrapper_label : null;
        existing.launched_with = live.launched_with !== undefined ? live.launched_with : null;
        if (live.pinned_theme) existing.pinned_theme = live.pinned_theme;
        existing.session_row_id = live.session_row_id !== undefined ? live.session_row_id : null;
        existing.parent_session_id = live.parent_session_id !== undefined
            ? live.parent_session_id : null;
        if (live.label !== undefined) existing.label = live.label;
        return true;
    }
    rows.unshift({
        name: tmuxName,
        created_by_cloude: createdByUs(live),
        created_at_epoch: live.created_at_epoch || 0,
        window_count: 1,
        is_active: true,
        session_id: liveId,
        status: liveStatus,
        unread: liveUnread,
        pinned_theme: live.pinned_theme || null,
        agent_family: live.agent_family !== undefined ? live.agent_family : null,
        agent_family_source: live.agent_family_source !== undefined
            ? live.agent_family_source : null,
        agent_wrapper_label: live.agent_wrapper_label !== undefined
            ? live.agent_wrapper_label : null,
        launched_with: live.launched_with !== undefined ? live.launched_with : null,
        session_row_id: live.session_row_id !== undefined ? live.session_row_id : null,
        parent_session_id: live.parent_session_id !== undefined ? live.parent_session_id : null,
        label: live.label !== undefined ? live.label : null,
        // nothing at all
        startup_gate: live.startup_gate,
        status_source: live.status_source,
        activity_hint: live.activity_hint !== undefined ? live.activity_hint : null,
        parked_summary: live.parked_summary !== undefined ? live.parked_summary : null,
        usage_limit: live.usage_limit ?? null,
        host_key: live.host_key ?? null,
        host_label: live.host_label ?? null,
        host_state: live.host_state ?? null,
    });
    return true;
}

export function mergeLiveSessions(
    rows: RunningSessionRow[],
    liveSessions: SessionListItem[],
): RunningSessionRow[] {
    for (const live of liveSessions) {
        mergeLiveSession(rows, live);
    }
    return rows;
}

/* could not */
export function filterDeadPanes(rows: RunningSessionRow[]): RunningSessionRow[] {
    return rows.filter((s) => !s || s.status !== 'dead');
}

export function rowsFromAttachable(
    list: unknown,
    listing: ListingState,
    malformedDetail: string,
): RunningSessionRow[] {
    if (Array.isArray(list)) {
        return list as AttachableSession[] as RunningSessionRow[];
    }
    noteListingUnknown(listing, 'attachable', 'malformed_response', malformedDetail);
    return [];
}

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

function settled<T>(run: () => Promise<T>): Promise<Settled<T>> {
    try {
        return run().then(
            (value): Settled<T> => ({ ok: true, value }),
            (error): Settled<T> => ({ ok: false, error }),
        );
    } catch (error) {
        return Promise.resolve({ ok: false, error });
    }
}

export async function loadRunningRows(deps: {
    host: {
        listAttachableSessions(): Promise<AttachableSession[]>;
        listSessions?(): Promise<SessionListItem[]>;
        getCurrentSession(): Promise<SessionListItem | null>;
    };
    t: Translate;
    malformedDetail: (t: Translate) => string;
    detailFor: (err: unknown, status: number | null, t: Translate) => string;
    reasonFor: (err: unknown, status: number | null) => string;
    statusFor: (err: unknown) => number | null;
    onReauth?: () => void;
}): Promise<{ rows: RunningSessionRow[]; listing: ListingState }> {
    const listing = emptyListing();
    let rows: RunningSessionRow[] = [];
    const attachable = settled(() => deps.host.listAttachableSessions());
    const live = typeof deps.host.listSessions === 'function'
        ? settled(() => deps.host.listSessions!())
        : null;
    const answeredAttachable = await attachable;
    if (answeredAttachable.ok) {
        rows = rowsFromAttachable(answeredAttachable.value, listing, deps.malformedDetail(deps.t));
    } else {
        const err = answeredAttachable.error;
        const status = deps.statusFor(err);
        console.error(
            'CloudeWeb: loadRunningSessions failed:',
            status !== null ? `status=${status}` : '(no status)',
            err,
        );
        if (status === 401 && deps.onReauth) deps.onReauth();
        rows = [];
        noteListingUnknown(
            listing, 'attachable',
            deps.reasonFor(err, status),
            deps.detailFor(err, status, deps.t),
        );
    }
    try {
        let liveSessions: SessionListItem[] = [];
        if (live) {
            const answeredLive = await live;
            if (!answeredLive.ok) throw answeredLive.error;
            liveSessions = answeredLive.value;
        }
        // no live sessions
        const listAnswered = live !== null && Array.isArray(liveSessions);
        if (!listAnswered) {
            const current = await deps.host.getCurrentSession();
            liveSessions = current ? [current] : [];
        }
        mergeLiveSessions(rows, liveSessions);
    } catch (err) {
        const status = deps.statusFor(err);
        if (status !== 404) {
            console.error('CloudeWeb: live-session merge failed:',
                status !== null ? `status=${status}` : '(no status)', err);
            noteListingUnknown(
                listing, 'live',
                deps.reasonFor(err, status),
                deps.detailFor(err, status, deps.t),
            );
        }
    }
    return { rows: filterDeadPanes(rows), listing };
}
