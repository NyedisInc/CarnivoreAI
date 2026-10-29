/** @vitest-environment jsdom */
import * as BrowserRows from '../drawer/browser-rows';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
    calls: [] as { path: string; body?: string }[],
    select: null as Record<string, unknown> | null,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string, init?: RequestInit) => {
            server.calls.push({ path: p, body: typeof init?.body === 'string' ? init.body : undefined });
            if (p === '/browsers/selected') return { select: server.select };
            if (p === '/browsers/open') {
                const page = { id: PAGE_ID, key: 'huddle_artifact:5:ab12cd34', src: '/api/v1/cplugs/huddle/artifact-view/t.sig', frame: 'sandboxed', title: 'Layout A' };
                return { page, select: { seq: 77, kind: 'page', page_id: PAGE_ID, title: 'Layout A', age_s: 0 } };
            }
            return {};
        },
    };
});

import TaskManagerArtifactCard from '../../cplugs/huddle/TaskManagerArtifactCard.svelte';
import { resourcePush } from '../resource-push/boot';
import { browsers } from './api.svelte';
import { followBrowserSelect, resetBrowserSelectForTest } from './select-push.svelte';
import { openPages } from './pages.svelte';

const ID = '0123456789abcdef';
const PAGE_ID = 'fedcba9876543210';

type G = Record<string, any>; // the legacy drawer globals are untyped by nature

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

describe('the browser select push', () => {
    let opened: string[];
    let closedAfterSwitch: number;
    let order: string[];

    beforeEach(() => {
        opened = [];
        closedAfterSwitch = 0;
        const g = globalThis as G;
        order = [];
        vi.spyOn(browsers, 'refresh').mockImplementation(async () => { order.push('refresh'); });
        vi.spyOn(openPages, 'refresh').mockImplementation(async () => { order.push('refresh pages'); });
        g.CloudeWeb = { browsers: { list: () => [], open: (id: string) => { order.push('open'); opened.push(id); return true; } } };
        g.SessionSidebar = { _closeAfterSwitch: () => { closedAfterSwitch += 1; } };
        server.calls = [];
        server.select = null;
        resetBrowserSelectForTest();
    });

    afterEach(() => {
        vi.restoreAllMocks();
        document.body.innerHTML = '';
    });

    test('a pushed pointer selects the sidebar row through its own activation, once', async () => {
        followBrowserSelect();
        await settle();
        expect(opened).toEqual([]);

        server.select = { seq: 11, browser_id: ID, title: 'release notes', age_s: 1 };
        const push = resourcePush();
        push.store.hello({ resource_topics: ['browser_select'] });
        push.store.frame({ topics: ['browser_select'] });
        await settle();

        expect(opened).toEqual([ID]);
        expect(closedAfterSwitch).toBe(1);
        expect(order).toEqual(['refresh', 'open']);

        push.store.frame({ topics: ['browser_select'] });
        server.select = { seq: 12, browser_id: ID, title: '', age_s: 600 };
        push.store.frame({ topics: ['browser_select'] });
        server.select = { seq: 13, browser_id: '../../x', title: '', age_s: 0 };
        push.store.frame({ topics: ['browser_select'] });
        await settle();
        expect(opened).toEqual([ID]);
    });

    test('a page pointer re-reads the PAGES list, then selects the page row through the same activation', async () => {
        followBrowserSelect();
        server.select = { seq: 21, kind: 'page', page_id: PAGE_ID, title: 'Layout A', age_s: 1 };
        const push = resourcePush();
        push.store.hello({ resource_topics: ['browser_select'] });
        push.store.frame({ topics: ['browser_select'] });
        await settle();
        expect(opened).toEqual([PAGE_ID]);
        expect(order).toEqual(['refresh pages', 'open']);
        server.select = { seq: 22, kind: 'page', page: { src: '/api/v1/x' }, title: '', age_s: 0 };
        push.store.frame({ topics: ['browser_select'] });
        await settle();
        expect(opened).toEqual([PAGE_ID]);
    });

    test("the card's open in tab asks the server to open the artifact and selects the page row it answers", async () => {
        followBrowserSelect();
        const target = document.createElement('div');
        document.body.appendChild(target);
        const app = mount(TaskManagerArtifactCard, {
            target, props: { itemId: 5, artifact: { id: 'ab12cd34', title: 'Layout A', description: '', size: 2048 } },
        });
        await settle();
        (document.querySelector('[data-task-manager-artifact-tab]') as HTMLButtonElement).click();
        await settle();
        const call = server.calls.find((c) => c.path === '/browsers/open');
        expect(JSON.parse(call?.body ?? '{}')).toEqual({ huddle_artifact: { item: 5, artifact: 'ab12cd34' }, title: 'Layout A' });
        expect(opened).toEqual([PAGE_ID]);
        expect(order).toEqual(['refresh pages', 'open']);
        unmount(app);
    });
});
