import { sessionUuidOfRow } from '../../opscenter/api/automations-widget.svelte';
import { listingRows } from '../../opscenter/api/poll.svelte';
import { uuidOfName } from '../drawer/group-membership';

export interface SessionRef {
    sessionId?: string | null;
    sessionRowId?: number | null;
    sessionUuid?: string | null;
    tmuxName?: string | null;
}

interface ListingRow {
    session_row_id?: number | null;
    session_uuid?: string | null;
    tmux_session?: string | null;
    session?: { id?: string } | null;
}

export async function sessionRefFor(sessionId: string): Promise<SessionRef> {
    const rows = await listingRows<ListingRow>('list', '/sessions/list');
    const row = rows.find((r) => r.session?.id === sessionId);
    if (!row) return { sessionId };
    return { sessionId, sessionRowId: row.session_row_id ?? null, sessionUuid: row.session_uuid ?? null, tmuxName: row.tmux_session ?? null };
}

export async function sessionUuidFor(ref: SessionRef): Promise<string | null> {
    if (ref.sessionUuid) return ref.sessionUuid;
    if (ref.tmuxName) {
        const joined = uuidOfName(ref.tmuxName);
        if (joined) return joined;
    }
    if (typeof ref.sessionRowId === 'number') return sessionUuidOfRow(ref.sessionRowId);
    return null;
}

const knownIds = new Map<string, string>();

export function rememberSessionId(uuid: string, sessionId: string | null | undefined): void {
    if (uuid && sessionId) knownIds.set(uuid, sessionId);
}

export async function sessionIdForUuid(uuid: string): Promise<string | null> {
    const known = knownIds.get(uuid);
    if (known) return known;
    const rows = await listingRows<ListingRow>('list', '/sessions/list');
    const id = rows.find((r) => r.session_uuid === uuid)?.session?.id ?? null;
    if (id) knownIds.set(uuid, id);
    return id;
}
