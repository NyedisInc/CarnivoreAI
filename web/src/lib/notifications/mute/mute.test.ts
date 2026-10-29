import { afterEach, describe, expect, it, vi } from 'vitest';

/** A localStorage good enough for the reads these modules make. */
function fakeStorage(seed: Record<string, string>) {
    const map = new Map(Object.entries(seed));
    return {
        getItem: (k: string): string | null => map.get(k) ?? null,
        setItem: (k: string, v: string): void => void map.set(k, v),
        removeItem: (k: string): void => void map.delete(k),
    };
}

function fakeHost() {
    const handlers: Array<(frame: unknown) => void> = [];
    return {
        client: {
            subscribe(handler: (frame: unknown) => void): () => void {
                handlers.push(handler);
                return () => void handlers.splice(handlers.indexOf(handler), 1);
            },
            isConnected: (): boolean => true,
        },
        deliver(frame: unknown): void {
            for (const handler of [...handlers]) handler(frame);
        },
    };
}

async function load(mutes: { everywhere: string[]; here: string[] }) {
    (globalThis as { localStorage?: unknown }).localStorage = fakeStorage({
        claude_tunnel_token: 'an-access-token',
        claude_refresh_token: 'a-refresh-token',
    });
    const host = fakeHost();
    (globalThis as { AppEvents?: unknown }).AppEvents = host.client;
    vi.resetModules();
    const { ScreenFilter } = await import('../screen-filter');
    const events = await import('../../../opscenter/api/events.svelte');
    const asked: string[] = [];
    const fetcher = (async (path: string) => {
        asked.push(path);
        if (path === '/notifications/types') return { types: [{ id: 'session.finished' }, { id: 'session.permission' }] };
        if (path === '/notifications/settings') return { screen: { 'session.finished': { value: true }, 'session.permission': { value: true } } };
        if (path.startsWith('/notifications/mutes')) return { device: null, devices: {}, ...mutes };
        throw new Error(`unexpected ${path}`);
    }) as never;
    const filter = new ScreenFilter(fetcher);
    await filter.refresh();
    return { filter, events, host, asked };
}

describe('mute hides the pop-up and never the status event', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        delete (globalThis as { localStorage?: unknown }).localStorage;
        delete (globalThis as { AppEvents?: unknown }).AppEvents;
    });

    it('a muted type shows no pop-up while its session.status frame still reaches its subscriber', async () => {
        const { filter, events, host, asked } = await load({ everywhere: ['session.finished'], here: [] });
        expect(asked.some((p) => p.startsWith('/notifications/mutes?device=b_'))).toBe(true);
        const got: Array<Record<string, unknown>> = [];
        const off = events.subscribe('session.status', (frame) => void got.push(frame as unknown as Record<string, unknown>));
        events.startEvents();

        host.deliver({ type: 'session.status', session_id: 'ses_a', status: 'finished_unread' });

        expect(filter.shows({ notify_type: 'session.finished' })).toBe(false);
        expect(got.map((f) => f.status)).toEqual(['finished_unread']);
        expect(filter.shows({ notify_type: 'session.permission' })).toBe(true);
        filter.applyMutes({ everywhere: [], here: ['session.permission'] });
        expect(filter.shows({ notify_type: 'session.permission' })).toBe(false);
        expect(filter.shows({ notify_type: 'session.finished' })).toBe(true);
        off();
        events.stop();
    });

    it('NEGATIVE CONTROL: with nothing muted the same type shows', async () => {
        const { filter } = await load({ everywhere: [], here: [] });
        expect(filter.shows({ notify_type: 'session.finished' })).toBe(true);
    });

    it('a muted type stays hidden when the settings read fails, and an already drawn card is taken down', async () => {
        const fetcher = (async (path: string) => {
            if (path === '/notifications/types') return { types: [{ id: 'session.finished' }] };
            if (path.startsWith('/notifications/mutes')) return { everywhere: ['session.finished'], here: [] };
            throw new Error('settings down');
        }) as never;
        const drawn = new Map<string, { notify_type?: string }>([['a', { notify_type: 'session.finished' }], ['b', {}]]);
        const dismissed: string[] = [];
        (globalThis as { ToastManager?: unknown }).ToastManager = {
            pruneHidden(shows: (t: unknown) => boolean) {
                for (const [id, t] of drawn) if (shows(t) === false) dismissed.push(id);
            },
        };
        const { ScreenFilter } = await import('../screen-filter');
        const filter = new ScreenFilter(fetcher);
        await filter.refresh();
        delete (globalThis as { ToastManager?: unknown }).ToastManager;
        expect(filter.shows({ notify_type: 'session.finished' })).toBe(false);
        expect(dismissed).toEqual(['a']);
    });
});
