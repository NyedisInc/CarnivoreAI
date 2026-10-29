
export interface SessionRecord {
    id?: number;
    session_uuid?: string;
    tmux_name?: string;
    tmux_created_epoch?: number;
    archived_at?: unknown;
    [field: string]: unknown;
}

export interface IdentityRow {
    name?: string;
    created_at_epoch?: number;
    session_row_id?: number | null;
    session_uuid?: string | null;
    [field: string]: unknown;
}

export interface RecordIndex {
    byRowId: Map<number, string>;
    byInstance: Map<string, string>;
    byName: Map<string, string | null>;
}

export function instanceKey(name: string | undefined, epoch: number | undefined): string | null {
    if (!name || !Number.isFinite(epoch) || (epoch as number) <= 0) return null;
    return `${name}@${epoch}`;
}

export function recordIndex(records: readonly SessionRecord[]): RecordIndex {
    const byRowId = new Map<number, string>();
    const byInstance = new Map<string, string>();
    const byName = new Map<string, string | null>();
    for (const r of Array.isArray(records) ? records : []) {
        if (!r || !r.session_uuid || !r.tmux_name) continue;
        if (typeof r.id === 'number') byRowId.set(r.id, r.session_uuid);
        const key = instanceKey(r.tmux_name, r.tmux_created_epoch);
        if (key) byInstance.set(key, r.session_uuid);
        if (r.archived_at) continue;
        byName.set(r.tmux_name, byName.has(r.tmux_name) ? null : r.session_uuid);
    }
    return { byRowId, byInstance, byName };
}

export function uuidFor(row: IdentityRow, index: RecordIndex): string | null {
    if (!row || !index) return null;
    if (typeof row.session_row_id === 'number' && index.byRowId.has(row.session_row_id)) {
        return index.byRowId.get(row.session_row_id) as string;
    }
    const key = instanceKey(row.name, row.created_at_epoch);
    if (key && index.byInstance.has(key)) return index.byInstance.get(key) as string;
    return (row.name && index.byName.get(row.name)) || null;
}

export function stamp(rows: IdentityRow[], records: readonly SessionRecord[]): number {
    const index = recordIndex(records);
    let n = 0;
    for (const row of Array.isArray(rows) ? rows : []) {
        if (!row.session_uuid) row.session_uuid = uuidFor(row, index);
        if (row.session_uuid) n += 1;
    }
    return n;
}

let lastNames: string | null = null;

export function namesChanged(rows: readonly IdentityRow[]): boolean {
    const sig = (Array.isArray(rows) ? rows : [])
        .map((r) => (r && r.name) || '').filter(Boolean).sort().join('\n');
    const changed = lastNames !== null && sig !== lastNames;
    lastNames = sig;
    return changed;
}

export function reset(): void {
    lastNames = null;
}
