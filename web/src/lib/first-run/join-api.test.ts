import { describe, expect, it, vi } from 'vitest';
import { fetchJoinStatus, pollJoinStatus } from './join-api';

const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

describe('fetchJoinStatus', () => {
    it('reads joined from a 200 (the route answers once the computer is joined)', async () => {
        const got = await fetchJoinStatus(reply(200, { state: 'joined', error: null, main_label: 'air', candidates: [] }));
        expect(got?.state).toBe('joined');
    });
    it('reads a 409 not_joinable as no status', async () => {
        expect(await fetchJoinStatus(reply(409, { detail: { reason: 'not_joinable' } }))).toBeNull();
    });
});

describe('pollJoinStatus', () => {
    it('walks linking then joined and stops at joined', async () => {
        vi.useFakeTimers();
        const states = ['linking', 'joined'];
        const seen: string[] = [];
        const read = async () => ({ state: states.shift() as 'linking' | 'joined', error: null, main_label: null, candidates: [] });
        pollJoinStatus((s) => {
            seen.push(s.state);
            return s.state === 'joined';
        }, read);
        await vi.advanceTimersByTimeAsync(5000);
        expect(seen).toEqual(['linking', 'joined']);
        vi.useRealTimers();
    });
});
