/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SyncPanel from './SyncPanel.svelte';
import { setLocale } from '../../i18n/index.svelte';
import { EMPTY_SYNC, type SyncBody, type SyncPeer } from './api';
import { peerState } from './logic';
import { sync } from './store.svelte';

setLocale('en');

const peer = (key: string, over: Partial<SyncPeer> = {}): SyncPeer => ({
    key, label: `computer ${key}`, enabled: true, protocol: 'ok', connected: true, last_exchange_at: 1760000000, last_result: 'ok', ...over,
});
const body = (peers: SyncPeer[], available = true): SyncBody => ({ available, peers });

interface Call { method: string; path: string; body: Record<string, unknown> | null }

function fake(initial: SyncBody, fail: string | null = null) {
    const calls: Call[] = [];
    let current = initial;
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        if (fail === `${method} ${path}`) throw new Error('sync broke');
        if (method === 'GET') return current;
        if (method === 'PUT') {
            const key = decodeURIComponent(path.split('/').pop()!);
            const enabled = JSON.parse(init.body as string).enabled;
            current = { ...current, peers: current.peers.map((p) => (p.key === key ? { ...p, enabled } : p)) };
            return current;
        }
        return { started: true };
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { sync.body = EMPTY_SYNC; sync.known = false; sync.problem = ''; sync.syncing = false; });
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
    vi.useRealTimers();
});

async function render(initial: SyncBody, fail: string | null = null) {
    const rig = fake(initial, fail);
    mounted.push(mount(SyncPanel, { target: document.body, props: { fetcher: rig.fetcher } }));
    await vi.waitFor(() => expect(sync.known || sync.problem !== '').toBe(true));
    flushSync();
    return rig;
}
const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const press = async (el: HTMLElement) => { el.click(); flushSync(); await Promise.resolve(); await Promise.resolve(); };
const state = (key: string) => q(`[data-sy-peer="${key}"] [data-sy="state"]`)!;

describe('the states', () => {
    test('each paired computer shows its label and the right state line', async () => {
        await render(body([
            peer('peer-a'),
            peer('peer-b', { last_result: 'refused' }),
            peer('peer-c', { protocol: 'older', last_result: 'older' }),
            peer('peer-d', { enabled: false, last_result: 'off' }),
            peer('peer-e', { connected: false, protocol: 'unknown', last_result: 'disconnected' }),
            peer('peer-f', { last_result: null, last_exchange_at: null }),
        ]));
        expect(document.body.textContent).toContain('computer peer-a');
        expect(state('peer-a').getAttribute('data-sy-state')).toBe('synced');
        expect(state('peer-a').textContent).toMatch(/^synced .+/);
        expect(state('peer-b').textContent).toBe('refused: that computer has not allowed sync yet');
        expect(state('peer-b').className).toContain('sy-state--bad');
        expect(state('peer-d').textContent).toBe('off');
        expect(state('peer-e').textContent).toBe('not connected');
        expect(state('peer-f').textContent).toBe('waiting for the first sync');
    });

    test('a computer on an older carnivore says so, even when its switch is on', async () => {
        await render(body([peer('peer-c', { protocol: 'older', last_result: 'older' })]));
        expect(state('peer-c').textContent).toBe('runs an older carnivore');
    });

    test('peerState puts the owner off switch before everything else', () => {
        expect(peerState(peer('x', { enabled: false, protocol: 'older', last_result: 'refused' }))).toBe('off');
        expect(peerState(peer('x', { last_result: 'rate_limited' }))).toBe('rate_limited');
        expect(peerState(peer('x', { last_result: 'no_change' }))).toBe('synced');
    });
});

describe('the actions', () => {
    test('the switch writes PUT /sync/peers/{key} with the other state and the row follows the answer', async () => {
        const rig = await render(body([peer('peer-a'), peer('peer-b')]));
        const sw = q('[data-sy-peer="peer-b"] [data-sy="switch"]') as HTMLButtonElement;
        expect(sw.getAttribute('aria-checked')).toBe('true');
        await press(sw);
        await vi.waitFor(() => expect(state('peer-b').textContent).toBe('off'));
        const put = rig.calls.find((c) => c.method === 'PUT')!;
        expect(put.path).toBe('/notifications/sync/peers/peer-b');
        expect(put.body).toEqual({ enabled: false });
        expect((q('[data-sy-peer="peer-a"] [data-sy="switch"]') as HTMLButtonElement).getAttribute('aria-checked')).toBe('true');
    });

    test('sync now posts to /sync/now and does not schedule a re-read of its own (the push covers it)', async () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const rig = await render(body([peer('peer-a')]));
        const gets = () => rig.calls.filter((c) => c.method === 'GET').length;
        const before = gets();
        await press(q('[data-sy="now"]')!);
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'POST' && c.path === '/notifications/sync/now')).toBe(true));
        await vi.advanceTimersByTimeAsync(5000);
        expect(gets()).toBe(before);
        flushSync();
        expect((q('[data-sy="now"]') as HTMLButtonElement).disabled).toBe(false);
    });
});

describe('empty, unavailable and error', () => {
    test('no paired computers shows the empty line and no sync now', async () => {
        await render(body([]));
        expect(q('[data-sy="empty"]')!.textContent).toContain('no paired computers');
        expect((q('[data-sy="now"]') as HTMLButtonElement).disabled).toBe(true);
        expect(q('[data-sy="peers"]')).toBeNull();
    });

    test('a sync service that is not running says so and offers no switches', async () => {
        await render(body([], false));
        expect(q('[data-sy="unavailable"]')!.textContent).toBe('sync is not running on this computer.');
        expect(q('[data-sy="now"]')).toBeNull();
    });

    test('a failed read is the problem line, not a blank panel', async () => {
        await render(body([peer('peer-a')]), 'GET /notifications/sync');
        expect(q('[data-sy="problem"]')!.textContent).toContain('sync broke');
        expect(q('[data-sy="peers"]')).toBeNull();
    });

    test('a failed switch write shows the problem line', async () => {
        await render(body([peer('peer-a')]), 'PUT /notifications/sync/peers/peer-a');
        await press(q('[data-sy="switch"]')!);
        await vi.waitFor(() => expect(q('[data-sy="problem"]')!.textContent).toContain('sync broke'));
    });
});

describe('theme safety', () => {
    test('the panel stylesheet names no literal colour, so every shipped theme restyles it through --oc-* tokens', () => {
        const css = readFileSync('src/lib/notifications/sync/sync.css', 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        const colours = css.match(/var\(--oc-[a-z0-9-]+\)/g) ?? [];
        expect(colours.length).toBeGreaterThan(3);
        expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
    });
});

describe('the trust line', () => {
    test('the panel says plainly that a paired computer can read and change the destinations, secrets included', async () => {
        await render(body([peer('peer-a')]));
        const line = q('[data-sy="trust"]')!;
        expect(line.textContent).toContain('can read and change these destinations');
        expect(line.textContent).toContain('secrets included');
    });

    test('it shows with no paired computer too', async () => {
        await render(body([]));
        expect(q('[data-sy="trust"]')).not.toBeNull();
    });
});
