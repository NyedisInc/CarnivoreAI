import { ApiError, authFetch } from '../sdk';
export type PointReason = 'kill' | 'remove' | 'sleep' | 'restart' | string;

export interface RestorePoint {
    readonly id: string;
    readonly takenAt: string;
    readonly reason: PointReason;
    readonly turns: number | null;
    readonly sizeBytes: number | null;
    readonly rawBytes: number | null;
    readonly pinned: boolean;
    readonly failsafe: boolean;
    readonly digest: Digest | null;
    readonly imported?: boolean;
    readonly labels?: readonly string[];
}

export interface Digest {
    readonly turns: number | null;
    readonly lengthMinutes: number | null;
    readonly compactions: number | null;
    readonly firstPrompt: string | null;
    readonly lastPrompt: string | null;
    readonly mostEdited: readonly string[];
}

export interface StoreSummary {
    readonly usedBytes: number;
    readonly capBytes: number;
    readonly pointCount: number;
    readonly pinnedCount: number;
    readonly keep: number | null;
    readonly bySession: Readonly<Record<string, number>> | null;
}

export interface SessionPoints {
    readonly points: readonly RestorePoint[];
    readonly digest: Digest | null;
}

export interface RestoreResult {
    readonly transcriptStatus: string;
    readonly sessionStatus: string;
    readonly sessionCode: string;
    readonly sessionUuid: string | null;
    readonly detail: string;
}

export type Answer<T> =
    | { readonly kind: 'ok'; readonly value: T }
    | { readonly kind: 'absent' }
    | { readonly kind: 'error'; readonly message: string };

export interface PointsApi {
    summary(): Promise<Answer<StoreSummary>>;
    points(sessionUuid: string): Promise<Answer<SessionPoints>>;
    pin(sessionUuid: string, pointId: string, pinned: boolean): Promise<Answer<null>>;
    restore(sessionUuid: string, pointId: string): Promise<Answer<RestoreResult>>;
}

export const SAVE_ROUTE = '/cplugs/save';

type Bag = Record<string, unknown>;

const isBag = (value: unknown): value is Bag => typeof value === 'object' && value !== null && !Array.isArray(value);

function pick(bag: Bag, ...keys: string[]): unknown {
    for (const key of keys) if (bag[key] !== undefined && bag[key] !== null) return bag[key];
    return undefined;
}

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && v !== '') : []);

export function readDigest(raw: unknown): Digest | null {
    if (!isBag(raw) || Object.keys(raw).length === 0) return null;
    const edited = pick(raw, 'files_most_edited', 'most_edited');
    const seconds = num(pick(raw, 'duration_seconds'));
    return {
        turns: num(pick(raw, 'turns')),
        lengthMinutes: seconds !== null ? seconds / 60 : num(pick(raw, 'length_minutes')),
        compactions: num(pick(raw, 'compactions')),
        firstPrompt: str(pick(raw, 'first_prompt')),
        lastPrompt: str(pick(raw, 'last_prompt')),
        mostEdited: Array.isArray(edited)
            ? edited.map((f) => (isBag(f) ? str(f['path']) : str(f))).filter((f): f is string => f !== null)
            : [],
    };
}

export function readPoint(raw: unknown): RestorePoint | null {
    if (!isBag(raw)) return null;
    const idRaw = pick(raw, 'id', 'point_id');
    const id = typeof idRaw === 'number' ? String(idRaw) : str(idRaw);
    const takenAt = str(pick(raw, 'created_at', 'taken_at', 'at'));
    if (!id || !takenAt) return null;
    const reason = str(pick(raw, 'reason', 'trigger')) ?? 'kill';
    return {
        id,
        takenAt,
        reason,
        turns: num(pick(raw, 'turns', 'turn_count')),
        sizeBytes: num(pick(raw, 'packed_bytes', 'disk_bytes', 'size_bytes')),
        rawBytes: num(pick(raw, 'raw_bytes', 'uncompressed_bytes')),
        pinned: pick(raw, 'pinned') === true,
        failsafe: pick(raw, 'kind') === 'current' || pick(raw, 'failsafe') === true,
        digest: readDigest(pick(raw, 'digest')),
        imported: pick(raw, 'imported') === true,
        labels: strings(pick(raw, 'labels')),
    };
}

export function readSummary(raw: unknown): StoreSummary {
    const bag = isBag(raw) ? raw : {};
    const per = pick(bag, 'by_session', 'per_session');
    let bySession: Record<string, number> | null = null;
    if (isBag(per)) {
        bySession = {};
        for (const [uuid, value] of Object.entries(per)) {
            const count = num(value) ?? (Array.isArray(value) ? value.length : null);
            if (count !== null) bySession[uuid] = count;
        }
    }
    return {
        usedBytes: num(pick(bag, 'used_bytes', 'total_bytes')) ?? 0,
        capBytes: num(pick(bag, 'cap_bytes', 'limit_bytes')) ?? 0,
        pointCount: num(pick(bag, 'points', 'point_count')) ?? 0,
        pinnedCount: num(pick(bag, 'pinned', 'pinned_count')) ?? 0,
        keep: num(pick(bag, 'max_points_per_conversation', 'keep')),
        bySession,
    };
}

export function readPoints(raw: unknown): SessionPoints {
    const bag = isBag(raw) ? raw : {};
    const list = Array.isArray(raw) ? raw : pick(bag, 'points', 'restore_points');
    const points = (Array.isArray(list) ? list : [])
        .map(readPoint)
        .filter((p): p is RestorePoint => p !== null)
        .sort((a, b) => Date.parse(b.takenAt) - Date.parse(a.takenAt));
    return { points, digest: points.find((p) => p.digest !== null)?.digest ?? null };
}

function failure<T>(error: unknown, readsOnly: boolean): Answer<T> {
    if (readsOnly && error instanceof ApiError && (error.status === 404 || error.status === 501)) return { kind: 'absent' };
    return { kind: 'error', message: error instanceof Error && error.message ? error.message : String(error) };
}

async function answer<T>(run: () => Promise<unknown>, read: (raw: unknown) => T, readsOnly = true): Promise<Answer<T>> {
    try {
        return { kind: 'ok', value: read(await run()) };
    } catch (error) {
        return failure<T>(error, readsOnly);
    }
}

const seg = (value: string): string => encodeURIComponent(value);

const pointsBase = (sessionUuid: string): string => `${SAVE_ROUTE}/sessions/${seg(sessionUuid)}/points`;

export const pointsApi: PointsApi = {
    summary: () => answer(() => authFetch(`${SAVE_ROUTE}/summary`), readSummary),
    points: (uuid) => answer(() => authFetch(pointsBase(uuid)), readPoints),
    pin: (uuid, id, pinned) =>
        answer(
            () => authFetch(`${pointsBase(uuid)}/${seg(id)}/pin`, { method: 'POST', body: JSON.stringify({ pinned }) }),
            () => null,
            false,
        ),
    restore: (uuid, id) =>
        answer(
            () => authFetch(`${pointsBase(uuid)}/${seg(id)}/restore`, { method: 'POST', body: JSON.stringify({}) }),
            (raw): RestoreResult => {
                const bag = isBag(raw) ? raw : {};
                const session = isBag(bag['session']) ? bag['session'] : {};
                return {
                    transcriptStatus: str(pick(bag, 'transcript_status')) ?? '',
                    sessionStatus: str(pick(session, 'status')) ?? 'not_attempted',
                    sessionCode: str(pick(session, 'code')) ?? '',
                    sessionUuid: str(pick(session, 'session_uuid')),
                    detail: str(pick(session, 'detail')) ?? '',
                };
            },
            false,
        ),
};
