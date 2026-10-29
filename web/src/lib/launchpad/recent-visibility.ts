
export interface RecentRow {
    id?: number | string | null;
    tmux_name?: string | null;
    archived_at?: string | null;
}

export interface LiveSession {
    name?: string | null;
    session_row_id?: number | string | null;
}

/* too rather than */
export function rowIdOf(live: LiveSession | null | undefined): number | null {
    if (!live) return null;
    const raw = live.session_row_id;
    if (raw === undefined || raw === null) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
}

export function isArchived(row: RecentRow | null | undefined): boolean {
    return !!(row && row.archived_at);
}

export function visibleRecentRows<T extends RecentRow>(
    recentRows: readonly T[] | null | undefined,
    liveSessions: readonly LiveSession[] | null | undefined,
): T[] {
    const rows = Array.isArray(recentRows) ? recentRows : [];
    const live = Array.isArray(liveSessions) ? liveSessions : [];
    if (!live.length) return rows.slice();

    const liveRowIds = new Set<number>();
    for (const s of live) {
        const id = rowIdOf(s);
        if (id !== null) liveRowIds.add(id);
    }
    const identityUnavailable = liveRowIds.size === 0;
    const liveNames: Set<string> | null = identityUnavailable
        ? new Set(live.map((s) => s && s.name).filter((n): n is string => !!n))
        : null;

    return rows.filter((row) => {
        if (isArchived(row)) return true;
        if (identityUnavailable) {
            return !(row && row.tmux_name && liveNames!.has(row.tmux_name));
        }
        const id = row && row.id;
        if (id === undefined || id === null) return true;
        return !liveRowIds.has(Number(id));
    });
}
