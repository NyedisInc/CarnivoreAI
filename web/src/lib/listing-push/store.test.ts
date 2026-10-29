import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LIVENESS, ListingStore, pushOrPoll, type Snapshot } from './store';

function snap(seq: number, stream = 's1'): Snapshot {
    return {
        stream,
        seq,
        collections: {
            list: {
                ok: true, status: null, detail: null, meta: {},
                rows: [
                    { tmux_session: 'a', activity_status: 'idle', running_context_used_pct: 10, session: { id: 'ses_a', working_dir: '/a' } },
                    { tmux_session: 'b', activity_status: 'idle', running_context_used_pct: 20, session: { id: 'ses_b', working_dir: '/b' } },
                ],
            },
            attachable: { ok: false, status: 503, detail: { listing_reason: 'probe_error' }, meta: {}, rows: [] },
            recent: { ok: true, status: null, detail: null, meta: { state: 'ok' }, rows: [] },
        },
    };
}

describe('ListingStore', () => {
    let fetches = 0;
    let next: Snapshot;
    let store: ListingStore;

    beforeEach(() => {
        fetches = 0;
        next = snap(3);
        store = new ListingStore({ fetchSnapshot: async () => { fetches += 1; return next; }, setTimer: () => 0 });
    });

    it('is not live, and answers null, until a snapshot lands', async () => {
        expect(store.isLive()).toBe(false);
        expect(store.rows('list')).toBeNull();
        await store.hello();
        expect(store.isLive()).toBe(true);
        expect(store.rows<{ session: { id: string } }>('list')!.map((r) => r.session.id)).toEqual(['ses_a', 'ses_b']);
        expect(store.meta('recent')).toEqual({ state: 'ok' });
        expect(store.rows('attachable')).toBeNull();
    });

    it('applies a delta field by field, keeping nulls and the nested level', async () => {
        await store.hello();
        const seen: string[][] = [];
        store.onChange((names) => seen.push(names));
        store.frame({ type: 'listing.delta', stream: 's1', seq: 4, changes: { list: {
            upsert: [
                { key: 'ses_a', fields: { activity_status: 'working', running_context_used_pct: null } },
                { key: 'ses_b', nested: { session: { working_dir: '/moved' } } },
            ],
        } } });
        const rows = store.rows<Record<string, unknown>>('list')!;
        expect(rows[0]!.activity_status).toBe('working');
        expect(rows[0]!.running_context_used_pct).toBeNull();
        expect(rows[0]!.session).toEqual({ id: 'ses_a', working_dir: '/a' });
        expect(rows[1]!.session).toEqual({ id: 'ses_b', working_dir: '/moved' });
        expect(seen).toEqual([['list']]);
        rows[0]!.activity_status = 'mutated';
        expect(store.rows<Record<string, unknown>>('list')![0]!.activity_status).toBe('working');
    });

    it('removes, reorders and turns a failed collection ok', async () => {
        await store.hello();
        store.frame({ type: 'listing.delta', stream: 's1', seq: 4, changes: {
            list: { remove: ['ses_a'], upsert: [{ key: 'ses_c', fields: { tmux_session: 'c', session: { id: 'ses_c' } } }], order: ['ses_c', 'ses_b'] },
            attachable: { status: { ok: true, status: null, detail: null, meta: {} }, upsert: [{ key: 'x', fields: { name: 'x' } }], order: ['x'] },
        } });
        expect(store.rows<{ session: { id: string } }>('list')!.map((r) => r.session.id)).toEqual(['ses_c', 'ses_b']);
        expect(store.rows('attachable')).toEqual([{ name: 'x' }]);
    });

    it('resyncs on a sequence gap and on a new stream, and ignores a duplicate', async () => {
        await store.hello();
        expect(fetches).toBe(1);
        store.frame({ type: 'listing.delta', stream: 's1', seq: 3, changes: { list: { remove: ['ses_a'] } } });
        expect(store.rows('list')!.length).toBe(2);
        next = snap(9);
        store.frame({ type: 'listing.delta', stream: 's1', seq: 6, changes: { list: { remove: ['ses_a'] } } });
        await store.resync();
        expect(fetches).toBe(2);
        next = snap(1, 's2');
        store.frame({ type: 'listing.delta', stream: 's2', seq: 10, changes: {} });
        await store.resync();
        expect(fetches).toBe(3);
        expect(store.isLive()).toBe(true);
    });

    it('stops answering when the socket closes, and stays down when the snapshot fails', async () => {
        await store.hello();
        store.closed();
        expect(store.isLive()).toBe(false);
        expect(store.rows('list')).toBeNull();
        const failing = new ListingStore({ fetchSnapshot: async () => { throw new Error('404'); }, setTimer: () => 0 });
        await failing.hello();
        expect(failing.isLive()).toBe(false);
    });
});

describe('pushOrPoll', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('polls only while the push is down and re-reads on a relevant delta', async () => {
        const store = new ListingStore({ fetchSnapshot: async () => snap(1), setTimer: () => 0 });
        const refresh = vi.fn();
        const stop = pushOrPoll(store, refresh, 5000, ['list']);
        vi.advanceTimersByTime(10_000);
        expect(refresh).toHaveBeenCalledTimes(2);
        await store.hello();
        expect(refresh).toHaveBeenCalledTimes(3);
        refresh.mockClear();
        vi.advanceTimersByTime(60_000);
        expect(refresh).not.toHaveBeenCalled();
        store.frame({ type: 'listing.delta', stream: 's1', seq: 2, changes: { recent: { upsert: [] } } });
        expect(refresh).not.toHaveBeenCalled();
        store.frame({ type: 'listing.delta', stream: 's1', seq: 3, changes: { list: { remove: ['ses_a'] } } });
        expect(refresh).toHaveBeenCalledTimes(1);
        store.closed();
        vi.advanceTimersByTime(5000);
        expect(refresh).toHaveBeenCalledTimes(2);
        stop();
        vi.advanceTimersByTime(20_000);
        expect(refresh).toHaveBeenCalledTimes(2);
        expect(LIVENESS).toBe('$live');
    });
});

describe('ListingStore resync spreading', () => {
    it('delays a re-hello by a random amount, and the first hello not at all', async () => {
        const timers: Array<{ fn: () => void; ms: number }> = [];
        let fetches = 0;
        const store = new ListingStore({
            fetchSnapshot: async () => { fetches += 1; return snap(1); },
            setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
            random: () => 0.5,
        });
        await store.hello();
        expect(fetches).toBe(1);
        const again = store.hello();
        expect(fetches).toBe(1);
        expect(timers).toHaveLength(1);
        expect(timers[0]!.ms).toBe(2000);
        timers[0]!.fn();
        await again;
        expect(fetches).toBe(2);
    });

    it('backs off a failing snapshot read, doubling with jitter up to a ceiling', async () => {
        const timers: Array<{ fn: () => void; ms: number }> = [];
        const store = new ListingStore({
            fetchSnapshot: async () => { throw new Error('down'); },
            setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
            random: () => 0,
        });
        vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        await store.hello();
        for (let i = 0; i < 5; i += 1) {
            timers[i]!.fn();
            await Promise.resolve();
            await Promise.resolve();
        }
        expect(timers.map((t) => t.ms)).toEqual([2500, 5000, 10000, 20000, 30000, 30000]);
    });
});
