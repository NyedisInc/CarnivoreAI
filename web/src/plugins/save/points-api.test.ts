import { beforeEach, describe, expect, test, vi } from 'vitest';

const { authFetch, calls, script } = vi.hoisted(() => {
    const calls: unknown[][] = [];
    const script: { next: () => Promise<unknown> } = { next: () => Promise.resolve({}) };
    return {
        calls,
        script,
        authFetch: (...args: unknown[]): Promise<unknown> => {
            calls.push(args);
            return script.next();
        },
    };
});
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    class ApiError extends Error {
        readonly status: number;
        constructor(message: string, status: number) {
            super(message);
            this.status = status;
        }
    }
    return { ...(await importOriginal<Record<string, unknown>>()), authFetch, ApiError };
});

import { ApiError } from '../../opscenter/api/auth.svelte';
import { readPoint, readPoints, readSummary, pointsApi } from './points-api';

beforeEach(() => {
    calls.length = 0;
    script.next = () => Promise.resolve({});
});

function failWith(error: Error): void {
    script.next = () => Promise.reject(error);
}

describe('normalising', () => {
    test('a point as the server sends it: packed and raw bytes, the digest inside', () => {
        const point = readPoint({
            id: '20260929T200742Z-kill', kind: 'point', created_at: '2026-09-29T20:07:42Z', reason: 'kill', turns: 12,
            raw_bytes: 700, packed_bytes: 100, disk_bytes: 130, pinned: true,
            digest: { turns: 12, duration_seconds: 5400, compactions: 1, first_prompt: 'hi', last_prompt: 'bye', files_most_edited: [{ path: 'a.py', edits: 4 }] },
        });
        expect(point).toMatchObject({ id: '20260929T200742Z-kill', takenAt: '2026-09-29T20:07:42Z', reason: 'kill', turns: 12, sizeBytes: 100, rawBytes: 700, pinned: true });
        expect(point?.digest).toEqual({ turns: 12, lengthMinutes: 90, compactions: 1, firstPrompt: 'hi', lastPrompt: 'bye', mostEdited: ['a.py'] });
    });

    test('an empty digest is no digest, and a point with no id or time is dropped, never drawn half empty', () => {
        expect(readPoint({ id: 'a', created_at: 't', digest: {} })?.digest).toBeNull();
        expect(readPoint({ created_at: 't' })).toBeNull();
        expect(readPoints({ points: [{ id: 'a' }, { id: 'b', created_at: '2026-01-01T00:00:00Z' }] }).points.map((p) => p.id)).toEqual(['b']);
    });

    test('points come newest first, and the session digest is the newest point that has one', () => {
        const list = [
            { id: 'old', created_at: '2026-01-01T00:00:00Z', digest: { turns: 1 } },
            { id: 'new', created_at: '2026-02-01T00:00:00Z', digest: {} },
        ];
        const got = readPoints({ points: list });
        expect(got.points.map((p) => p.id)).toEqual(['new', 'old']);
        expect(got.digest?.turns).toBe(1);
    });

    test('summary: the real server fields', () => {
        expect(readSummary({ used_bytes: 5, history_bytes: 3, cap_bytes: 10, conversations: 3, points: 2, current_backups: 1, pinned: 1, pinned_bytes: 4, max_points_per_conversation: 10, codec: 'zstd' })).toEqual({
            usedBytes: 5, historyBytes: 3, capBytes: 10, pointCount: 2, pinnedCount: 1, keep: 10,
        });
        expect(readSummary(null)).toEqual({ usedBytes: 0, historyBytes: 0, capBytes: 0, pointCount: 0, pinnedCount: 0, keep: null });
    });
});

describe('the calls', () => {
    test('404 and 501 on a read are absent', async () => {
        failWith(new ApiError('nope', 404));
        expect(await pointsApi.summary()).toEqual({ kind: 'absent' });
        failWith(new ApiError('nope', 501));
        expect(await pointsApi.points('u')).toEqual({ kind: 'absent' });
    });

    test('any other failure is an error carrying its words', async () => {
        failWith(new ApiError('disk full', 500));
        expect(await pointsApi.summary()).toEqual({ kind: 'error', message: 'disk full' });
    });

    test('a refused pin or restore is an error with the server\'s sentence, even on a 404 or 501', async () => {
        failWith(new ApiError('no restore point p9 for this session', 404));
        expect(await pointsApi.pin('u', 'p9', true)).toEqual({ kind: 'error', message: 'no restore point p9 for this session' });
        failWith(new ApiError('a transcript for this conversation already exists', 409));
        expect(await pointsApi.restore('u', 'p1')).toEqual({ kind: 'error', message: 'a transcript for this conversation already exists' });
    });

    test('a restore answer tells the transcript and the session apart', async () => {
        script.next = () => Promise.resolve({ transcript_status: 'written', session: { status: 'refused', code: 'grant_needed', session_uuid: 'u2', detail: 'the plugin needs the sessions.create permission' } });
        expect(await pointsApi.restore('u', 'p1')).toEqual({
            kind: 'ok', value: { transcriptStatus: 'written', sessionStatus: 'refused', sessionCode: 'grant_needed', sessionUuid: 'u2', detail: 'the plugin needs the sessions.create permission' },
        });
    });

    test('each call hits its documented route with the documented body', async () => {
        await pointsApi.summary();
        await pointsApi.points('u 1');
        await pointsApi.pin('u1', 'p1', true);
        await pointsApi.restore('u1', 'p1');
        expect(
            calls.map((c) => {
                const init = c[1] as { method?: string; body?: string } | undefined;
                return [c[0], init?.method ?? 'GET', init?.body ?? null];
            }),
        ).toEqual([
            ['/cplugs/save/summary', 'GET', null],
            ['/cplugs/save/sessions/u%201/points', 'GET', null],
            ['/cplugs/save/sessions/u1/points/p1/pin', 'POST', '{"pinned":true}'],
            ['/cplugs/save/sessions/u1/points/p1/restore', 'POST', '{}'],
        ]);
    });
});
