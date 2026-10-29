/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return {
        pages: [] as Record<string, unknown>[],
        sockets: [] as string[],
        popped: [] as string[],
        pagesGate: null as Promise<void> | null,
        writes: [] as string[],
    };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string, init?: RequestInit) => {
            if (init?.method && init.method !== 'GET') server.writes.push(`${init.method} ${p}`);
            if (p === '/browsers/pages') {
                if (server.pagesGate) await server.pagesGate;
                return { pages: server.pages.map((page) => ({ ...page })) };
            }
            if (p === '/browsers') return { browsers: [] };
            return {};
        },
    };
});
vi.mock('./browser-socket', () => ({
    openBrowserSocket: (id: string) => {
        server.sockets.push(id);
        return { send: () => {}, reopen: () => {}, close: () => {} };
    },
}));
vi.mock('./pop-out', () => ({
    popOutItem: async (id: string) => {
        server.popped.push(id);
        return true;
    },
}));

import { t } from '../i18n/index.svelte';
import BrowserScreen from './BrowserScreen.svelte';
import { openPages } from './pages.svelte';

const PAGE_ID = 'fedcba9876543210';
const BROWSER_ID = '0123456789abcdef';
const ARTIFACT = {
    id: PAGE_ID, key: 'huddle_artifact:5:ab12cd34', frame: 'sandboxed', title: 'Layout A', opened_at: 1,
    src: '/api/v1/cplugs/huddle/artifact-view/t1.sig',
};

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

describe('the browser screen with pages', () => {
    let app: ReturnType<typeof mount> | null = null;
    let screen: { show(id: string): void; close(): void; showing(): string | null };
    let dismissed: number;
    let titles: string[];

    beforeEach(async () => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        server.pages = [ARTIFACT];
        server.sockets = [];
        server.popped = [];
        dismissed = 0;
        titles = [];
        server.pagesGate = null;
        await openPages.refresh(true);
        const target = document.createElement('div');
        document.body.appendChild(target);
        app = mount(BrowserScreen, { target, props: { onDismiss: () => { dismissed += 1; screen.close(); }, onTitle: (title: string) => { titles.push(title); } } }) as never;
        screen = app as never;
        await settle();
    });

    afterEach(() => {
        if (app) unmount(app);
        app = null;
        document.body.innerHTML = '';
        vi.unstubAllGlobals();
    });

    test('a listed page is framed in the screen, sandboxed, and opens no browser socket', async () => {
        screen.show(PAGE_ID);
        await settle();
        const frame = document.querySelector('.bscreen iframe') as HTMLIFrameElement;
        expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
        expect(frame.getAttribute('src')).toBe(ARTIFACT.src);
        expect(document.querySelector('.bs-head, .bs-title, .bs-close, [data-browser-screen-popout]')).toBeNull();
        expect(document.querySelector('.bscreen button')).toBeNull();
        expect(server.sockets).toEqual([]);
    });

    test('the frame loads the ticket from the list read made on show, and a later refresh does not reload it', async () => {
        server.pages = [{ ...ARTIFACT, src: '/api/v1/cplugs/huddle/artifact-view/t2.sig' }];
        screen.show(PAGE_ID);
        await settle();
        const frame = document.querySelector('.bscreen iframe') as HTMLIFrameElement;
        expect(frame.getAttribute('src')).toBe('/api/v1/cplugs/huddle/artifact-view/t2.sig');
        server.pages = [{ ...ARTIFACT, src: '/api/v1/cplugs/huddle/artifact-view/t3.sig' }];
        await openPages.refresh(true);
        await settle();
        expect((document.querySelector('.bscreen iframe') as HTMLIFrameElement).getAttribute('src')).toBe('/api/v1/cplugs/huddle/artifact-view/t2.sig');
    });

    test('an id the pages list does not carry is a remote browser: its socket opens, no frame', async () => {
        screen.show(BROWSER_ID);
        await settle();
        expect(server.sockets).toEqual([BROWSER_ID]);
        expect(document.querySelector('.bscreen iframe')).toBeNull();
    });

    test('a page closed on another window takes the screen down', async () => {
        screen.show(PAGE_ID);
        await settle();
        server.pages = [];
        await openPages.refresh(true);
        await settle();
        expect(dismissed).toBe(1);
        expect(document.querySelector('.bscreen')).toBeNull();
    });

    test('a page is never named a proxy browser, not even while its fresh read is out', async () => {
        let release: () => void = () => {};
        server.pagesGate = new Promise<void>((resolve) => { release = resolve; });
        const region = (): string => document.querySelector('.bscreen')!.getAttribute('aria-label') ?? '';
        try {
            screen.show(PAGE_ID);
            await settle();
            expect(titles).toEqual([ARTIFACT.title]);
            expect(region()).toBe(t('browser.screen.page', { label: ARTIFACT.title }));
        } finally {
            server.pagesGate = null;
            release();
        }
        await settle();
        expect(document.querySelector('.bscreen iframe')).not.toBeNull();
        expect(titles.every((title) => !title.includes('proxy'))).toBe(true);
        expect(region()).not.toContain('proxy');
    });

    test('a page with no title is called a page, never a proxy browser', async () => {
        server.pages = [{ ...ARTIFACT, title: '' }];
        await openPages.refresh(true);
        screen.show(PAGE_ID);
        await settle();
        expect(titles.length).toBeGreaterThan(0);
        expect(titles.every((title) => title === t('browser.page.untitled'))).toBe(true);
        expect(document.querySelector('.bscreen')!.getAttribute('aria-label')).toBe(t('browser.screen.page', { label: t('browser.page.untitled') }));
    });

    test('a proxy browser is still named one once it is known', async () => {
        screen.show(BROWSER_ID);
        await settle();
        expect(titles.at(-1)).toBe(t('browser.page'));
        expect(document.querySelector('.bscreen')!.getAttribute('aria-label')).toBe(t('browser.screen', { label: t('browser.page') }));
    });
});

describe('the proxy browser screen close key (#2607)', () => {
    test('a close key on the proxy browser asks first, then calls DELETE once and dismisses', async () => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        server.writes = [];
        const confirm = vi.fn(async () => true);
        (window as unknown as { App: unknown }).App = { showConfirmModal: confirm };
        let dismissed = 0;
        const target = document.createElement('div');
        document.body.appendChild(target);
        const app = mount(BrowserScreen, { target, props: { onDismiss: () => { dismissed += 1; } } }) as unknown as { show(id: string): void };
        app.show(BROWSER_ID);
        await settle();
        (document.querySelector('[data-bv-close]') as HTMLButtonElement).click();
        await settle();
        expect(confirm).toHaveBeenCalledTimes(1);
        expect(server.writes.filter((c) => c === `DELETE /browsers/${BROWSER_ID}`)).toHaveLength(1);
        expect(dismissed).toBe(1);
        unmount(app as never);
        delete (window as unknown as { App?: unknown }).App;
        document.body.innerHTML = '';
        vi.unstubAllGlobals();
    });
});
