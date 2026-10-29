import type { RunningSessionRow, SessionRecord, Translate } from './types';

export const INSTANCE_KEY_SEPARATOR = '\u0000';

export interface ResolvedAttribution {
    byName: Map<string, SessionRecord>;
    byInstance: Map<string, SessionRecord>;
    ambiguous: Set<string>;
}

export function instanceKey(name: string, epoch: number | string): string {
    return name + INSTANCE_KEY_SEPARATOR + epoch;
}

/* could not */
export function resolveSessionAttribution(rows: SessionRecord[]): ResolvedAttribution {
    const byInstance = new Map<string, SessionRecord>();
    const instanceCollisions = new Set<string>();
    const candidatesByName = new Map<string, Array<{ row: SessionRecord; epoch: number | null }>>();

    for (const row of rows) {
        if (!row || !row.tmux_name) continue;
        const name = row.tmux_name;
        const epoch = (row.tmux_created_epoch === null || row.tmux_created_epoch === undefined)
            ? null
            : row.tmux_created_epoch;

        if (epoch !== null) {
            const key = instanceKey(name, epoch);
            if (byInstance.has(key)) {
                instanceCollisions.add(key);
            } else {
                byInstance.set(key, row);
            }
        }

        if (row.archived_at) continue;

        if (!candidatesByName.has(name)) candidatesByName.set(name, []);
        candidatesByName.get(name)!.push({ row, epoch });
    }

    for (const key of instanceCollisions) byInstance.delete(key);

    const byName = new Map<string, SessionRecord>();
    const ambiguous = new Set<string>();
    for (const [name, candidates] of candidatesByName) {
        if (candidates.length === 1) {
            byName.set(name, candidates[0]!.row);
            continue;
        }
        if (candidates.some((c) => c.epoch === null)) {
            ambiguous.add(name);
            continue;
        }
        const maxEpoch = Math.max(...candidates.map((c) => c.epoch as number));
        const winners = candidates.filter((c) => c.epoch === maxEpoch);
        if (winners.length > 1) {
            ambiguous.add(name);
            continue;
        }
        byName.set(name, winners[0]!.row);
    }

    return { byName, byInstance, ambiguous };
}

export function buildWorkStampIndex(rows: SessionRecord[] | unknown): Map<string, string> {
    const index = new Map<string, string>();
    for (const row of (Array.isArray(rows) ? rows : []) as SessionRecord[]) {
        if (!row || !row.tmux_name || !row.last_work_at) continue;
        const seen = index.get(row.tmux_name);
        if (!seen || row.last_work_at > seen) {
            index.set(row.tmux_name, row.last_work_at);
        }
    }
    return index;
}

export function workStampFor(
    session: RunningSessionRow | null | undefined,
    index: Map<string, string> | null | undefined,
): string | null {
    if (!session || !session.name) return null;
    if (!index) return null;
    return index.get(session.name) || null;
}

export function sortRunningSessionsByWork(
    rows: RunningSessionRow[],
    index: Map<string, string> | null | undefined,
): RunningSessionRow[] {
    rows.sort((a, b) => {
        const aw = workStampFor(a, index);
        const bw = workStampFor(b, index);
        if (!!aw !== !!bw) return aw ? -1 : 1;
        if (aw && bw && aw !== bw) return aw < bw ? 1 : -1;
        if (!!a.created_by_cloude !== !!b.created_by_cloude) {
            return a.created_by_cloude ? -1 : 1;
        }
        return (b.created_at_epoch || 0) - (a.created_at_epoch || 0);
    });
    return rows;
}

export interface AttributionSnapshot {
    byName: Map<string, SessionRecord>;
    byInstance: Map<string, SessionRecord>;
    ambiguous: Set<string>;
    records: SessionRecord[];
    workStamps: Map<string, string>;
    listingOk: boolean;
    listingDetail: string | null;
}

export function emptyAttribution(detail: string): AttributionSnapshot {
    return {
        byName: new Map(),
        byInstance: new Map(),
        ambiguous: new Set(),
        records: [],
        workStamps: new Map(),
        listingOk: false,
        listingDetail: detail,
    };
}

export async function loadAttribution(
    host: { listSessionRecords(): Promise<SessionRecord[]> },
    t: Translate,
    malformedDetail: (t: Translate) => string,
    failedDetail: (error: unknown, t: Translate) => string,
): Promise<AttributionSnapshot> {
    try {
        const rows = await host.listSessionRecords();
        if (!Array.isArray(rows)) {
            return emptyAttribution(malformedDetail(t));
        }
        const resolved = resolveSessionAttribution(rows);
        return {
            byName: resolved.byName,
            byInstance: resolved.byInstance,
            ambiguous: resolved.ambiguous,
            records: rows,
            workStamps: buildWorkStampIndex(rows),
            listingOk: true,
            listingDetail: null,
        };
    } catch (error) {
        console.warn('CloudeWeb: failed to load session attribution:', error);
        return emptyAttribution(failedDetail(error, t));
    }
}
