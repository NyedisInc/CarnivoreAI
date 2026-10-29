import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearDataCache, readCached, setCacheBackend, writeCached, type CacheBackend } from '../data-cache/cache';
import { LISTING_CACHE_KEY, hydrateAndPersist } from './cache';
import { ListingStore, type Snapshot } from './store';

function token(sub: string): string {
    const body = btoa(JSON.stringify({ sub })).replace(/=+$/, '');
    return `h.${body}.s`;
}

function memoryBackend(): CacheBackend & { map: Map<string, unknown> } {
    const map = new Map<string, unknown>();
    return {
        map,
        get: async (key) => map.get(key),
        put: async (key, value) => { map.set(key, value); },
        clear: async () => { map.clear(); },
    };
}

function snapshot(status: string, name: string): Snapshot {
    return {
        stream: 's1', seq: 1,
        collections: {
            list: {
                rows: [{ session: { id: 'ses_1', name }, activity_status: status, status_source: 'registry', unread: true, startup_gate: 'open' }],
                ok: true, status: null, detail: null, meta: {},
            },
        },
    };
}

let backend: ReturnType<typeof memoryBackend>;
let sub = 'alice';

beforeEach(() => {
    backend = memoryBackend();
    setCacheBackend(backend);
    sub = 'alice';
    vi.stubGlobal('localStorage', { getItem: () => token(sub) });
    vi.stubGlobal('location', { origin: 'https://mac.local:8000' });
});
afterEach(() => {
    setCacheBackend(null);
    vi.unstubAllGlobals();
});

describe('listing first paint from the browser cache', () => {
    it('paints the cached listing before the network answers, then the live answer replaces it', async () => {
        await writeCached(LISTING_CACHE_KEY, snapshot('working', 'saved name'));

        let answer!: (s: Snapshot) => void;
        const network = new Promise<Snapshot>((resolve) => { answer = resolve; });
        const store = new ListingStore({ fetchSnapshot: () => network });
        await hydrateAndPersist(store);

        expect(store.isLive()).toBe(false);
        expect(store.rows('list')).toBeNull();
        const painted = store.provisionalRows<Record<string, unknown>>('list');
        expect(painted).toHaveLength(1);
        expect(painted![0]).toMatchObject({
            provisional: true, activity_status: 'unknown', status_source: 'none', unread: null, startup_gate: null,
        });
        expect((painted![0]!.session as { name: string }).name).toBe('saved name');

        const resync = store.hello();
        answer(snapshot('idle', 'live name'));
        await resync;
        const live = store.rows<Record<string, unknown>>('list')!;
        expect(live[0]).toMatchObject({ activity_status: 'idle', status_source: 'registry' });
        expect(live[0]!.provisional).toBeUndefined();
        expect(store.provisionalRows('list')).toBeNull();
    });

    it('never shows another identity the copy, and sign-out clears it', async () => {
        await writeCached(LISTING_CACHE_KEY, snapshot('working', 'alice list'));
        sub = 'bob';
        expect(await readCached(LISTING_CACHE_KEY)).toBeNull();
        sub = 'alice';
        expect(await readCached(LISTING_CACHE_KEY)).not.toBeNull();
        await clearDataCache();
        expect(await readCached(LISTING_CACHE_KEY)).toBeNull();
    });

    it('works normally when the cache is unusable', async () => {
        const broken: CacheBackend = {
            get: async () => { throw new Error('boom'); },
            put: async () => { throw new Error('boom'); },
            clear: async () => { throw new Error('boom'); },
        };
        setCacheBackend(broken);
        vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        const store = new ListingStore({ fetchSnapshot: async () => snapshot('idle', 'live') });
        await hydrateAndPersist(store);
        expect(store.provisionalRows('list')).toBeNull();
        await store.hello();
        expect(store.rows('list')).toHaveLength(1);
        expect(await writeCached('x', { a: 1 })).toBe(false);
    });
});
