/* start a session */
import { ApiError, authFetch } from '../sdk';
export type PointReason = 'kill' | 'remove' | 'sleep' | 'restart' | 'clear' | string;

export interface RestorePoint {
    readonly id: string;
    readonly takenAt: string;
    readonly reason: PointReason;
    readonly turns: number | null;
    readonly sizeBytes: number | null;
    readonly rawBytes: number | null;
    readonly pinned: boolean;
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
    readonly historyBytes: number;
    readonly capBytes: number;
    readonly pointCount: number;
    readonly pinnedCount: number;
    readonly keep: number | null;
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

interface RawDigest {
    turns?: unknown;
    duration_seconds?: unknown;
    compactions?: unknown;
    first_prompt?: unknown;
    last_prompt?: unknown;
    files_most_edited?: unknown;
}

interface RawPoint {
    id?: unknown;
    created_at?: unknown;
    reason?: unknown;
    turns?: unknown;
    packed_bytes?: unknown;
    raw_bytes?: unknown;
    pinned?: unknown;
    digest?: unknown;
    imported?: unknown;
    labels?: unknown;
}

interface RawSummary {
    used_bytes?: unknown;
    history_bytes?: unknown;
    cap_bytes?: unknown;
    points?: unknown;
    pinned?: unknown;
    max_points_per_conversation?: unknown;
}

const isBag = (value: unknown): value is Bag => typeof value === 'object' && value !== null && !Array.isArray(value);

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && v !== '') : []);

export function readDigest(raw: unknown): Digest | null {
    if (!isBag(raw) || Object.keys(raw).length === 0) return null;
    const digest: RawDigest = raw;
    const edited = digest.files_most_edited;
    const seconds = num(digest.duration_seconds);
    return {
        turns: num(digest.turns),
        lengthMinutes: seconds !== null ? seconds / 60 : null,
        compactions: num(digest.compactions),
        firstPrompt: str(digest.first_prompt),
        lastPrompt: str(digest.last_prompt),
        mostEdited: Array.isArray(edited)
            ? edited.map((f) => (isBag(f) ? str(f['path']) : str(f))).filter((f): f is string => f !== null)
            : [],
    };
}

export function readPoint(raw: unknown): RestorePoint | null {
    if (!isBag(raw)) return null;
    const point: RawPoint = raw;
    const id = str(point.id);
    const takenAt = str(point.created_at);
    if (!id || !takenAt) return null;
    return {
        id,
        takenAt,
        reason: str(point.reason) ?? 'kill',
        turns: num(point.turns),
        sizeBytes: num(point.packed_bytes),
        rawBytes: num(point.raw_bytes),
        pinned: point.pinned === true,
        digest: readDigest(point.digest),
        imported: point.imported === true,
        labels: strings(point.labels),
    };
}

export function readSummary(raw: unknown): StoreSummary {
    const summary: RawSummary = isBag(raw) ? raw : {};
    return {
        usedBytes: num(summary.used_bytes) ?? 0,
        historyBytes: num(summary.history_bytes) ?? 0,
        capBytes: num(summary.cap_bytes) ?? 0,
        pointCount: num(summary.points) ?? 0,
        pinnedCount: num(summary.pinned) ?? 0,
        keep: num(summary.max_points_per_conversation),
    };
}

export function readPoints(raw: unknown): SessionPoints {
    const list = isBag(raw) ? raw['points'] : undefined;
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
                    transcriptStatus: str(bag['transcript_status']) ?? '',
                    sessionStatus: str(session['status']) ?? 'not_attempted',
                    sessionCode: str(session['code']) ?? '',
                    sessionUuid: str(session['session_uuid']),
                    detail: str(session['detail']) ?? '',
                };
            },
            false,
        ),
};
