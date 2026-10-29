/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import StatsCollectionPanel from './StatsCollectionPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import { sizeText, type Fetcher, type Maintenance } from './stats-collection/api';

setLocale('en');

interface Call { path: string; method: string; body: Record<string, unknown> | null }

function harness(enabled: boolean) {
    const state: Maintenance = {
        enabled, revision: 3, db_bytes: 1_546_188_226,
        clear: { state: 'idle', phase: '', bytes_before: null, bytes_after: null, reclaimed_bytes: null, error: '' },
        backfill: { state: 'idle', pending_sources: 0, known_sources: 0 },
    };
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        if (path === '/stats/settings') { state.enabled = Boolean(call.body!.enabled); state.revision += 1; }
        if (path === '/stats/clear') {
            state.db_bytes = 300_000;
            state.clear = { state: 'done', phase: '', bytes_before: 1_546_188_226, bytes_after: 300_000, reclaimed_bytes: 1_545_888_226, error: '' };
        }
        if (path === '/stats/backfill') state.backfill = { state: 'running', pending_sources: 4, known_sources: 9 };
        return structuredClone(state);
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(h: ReturnType<typeof harness>, extra: { part?: 'all' | 'main' | 'lifecycle' } = {}) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(StatsCollectionPanel, { target, props: { fetcher: h.fetcher, pollMs: 0, ...extra } }));
    await settle();
    return target;
}

const $1 = (root: ParentNode, sel: string): HTMLElement => {
    const el = root.querySelector<HTMLElement>(sel);
    expect(el, `no element for ${sel}`).toBeTruthy();
    return el!;
};

describe('stats collection panel', () => {
    test('size text', () => {
        expect(sizeText(1_546_188_226)).toBe('1.4 gb');
        expect(sizeText(512)).toBe('512 b');
    });

    test('off: switch patches the route, clear needs a confirm, then shows what was reclaimed', async () => {
        const h = harness(false);
        const root = await render(h);
        expect($1(root, '[data-stats="switch"]').getAttribute('aria-checked')).toBe('false');
        expect(root.querySelector('[data-stats="backfill"]')).toBeNull();
        $1(root, '[data-stats="clear"]').click();
        await settle();
        expect(h.calls.some((c) => c.path === '/stats/clear')).toBe(false);
        expect($1(root, '[data-stats="warn"]').textContent).toContain('1.4 gb');
        $1(root, '[data-stats="cancel"]').click();
        await settle();
        expect(root.querySelector('[data-stats="warn"]')).toBeNull();
        $1(root, '[data-stats="clear"]').click();
        await settle();
        $1(root, '[data-stats="confirm"]').click();
        await settle();
        expect(h.calls.filter((c) => c.path === '/stats/clear').map((c) => c.body)).toEqual([{ confirm: true }]);
        expect($1(root, '[data-stats="clear-done"]').textContent!.trim()).toBe('cleared. 1.4 gb reclaimed (1.4 gb before, 293.0 kb after).');
    });

    test('on: backfill posts a fresh key and shows progress; the switch sends the revision it read', async () => {
        const h = harness(true);
        const root = await render(h);
        expect(root.querySelector('[data-stats="clear"]')).toBeNull();
        $1(root, '[data-stats="backfill"]').click();
        await settle();
        const post = h.calls.find((c) => c.path === '/stats/backfill')!;
        expect(String(post.body!.idempotency_key)).toMatch(/^[A-Za-z0-9_.-]{8,128}$/);
        expect($1(root, '[data-stats="backfill-progress"]').textContent?.trim()).toBe('catching up: 4 of 9 sources left.');
        $1(root, '[data-stats="switch"]').click();
        await settle();
        expect(h.calls.find((c) => c.path === '/stats/settings')!.body).toEqual({ enabled: false, revision: 3 });
    });
});
