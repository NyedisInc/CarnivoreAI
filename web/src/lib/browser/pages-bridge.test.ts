/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return { calls: [] as string[], pages: [] as Record<string, unknown>[] };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string, init?: RequestInit) => {
            server.calls.push(`${init?.method ?? 'GET'} ${p}`);
            if (p === '/browsers/pages' && !init?.method) return { pages: server.pages.map((page) => ({ ...page })) };
            if (p === '/browsers' && !init?.method) return { browsers: [] };
            return undefined;
        },
    };
});

import { browserBridge } from './screen-host';
import { openPages } from './pages.svelte';

const PAGE_ID = 'fedcba9876543210';
const BROWSER_ID = '0123456789abcdef';

beforeEach(async () => {
    server.pages = [{ id: PAGE_ID, key: 'app:/static/popout.html?tab=flow', frame: 'app', title: 'flow', opened_at: 1, src: '/static/popout.html?tab=flow' }];
    await openPages.refresh(true);
    server.calls = [];
});

describe('the drawer bridge', () => {
    test('carries the held pages beside the browsers', () => {
        expect(browserBridge.pages().map((p) => p.id)).toEqual([PAGE_ID]);
        expect(browserBridge.list()).toEqual([]);
    });

    test('closes a page through the pages route, then re-reads', async () => {
        server.pages = [];
        await browserBridge.close(PAGE_ID);
        expect(server.calls).toContain(`DELETE /browsers/pages/${PAGE_ID}`);
        expect(server.calls.some((c) => c === `DELETE /browsers/${PAGE_ID}`)).toBe(false);
        expect(server.calls).toContain('GET /browsers/pages');
    });

    test('closes a browser through the browsers route', async () => {
        await browserBridge.close(BROWSER_ID);
        expect(server.calls).toContain(`DELETE /browsers/${BROWSER_ID}`);
        expect(server.calls.some((c) => c.startsWith('DELETE /browsers/pages'))).toBe(false);
    });

    test('a page keeps the title it was opened with', async () => {
        await expect(browserBridge.rename(PAGE_ID, 'other')).rejects.toThrow(/browser\.page\.rename_locked|keeps the title/);
        expect(server.calls.some((c) => c.startsWith('PATCH'))).toBe(false);
    });
});
