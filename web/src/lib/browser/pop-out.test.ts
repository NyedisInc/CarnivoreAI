/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return { pages: [] as Record<string, unknown>[], browsers: [] as Record<string, unknown>[], reads: 0 };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string) => {
            if (p === '/browsers/pages') {
                server.reads += 1;
                return { pages: server.pages.map((page) => ({ ...page })) };
            }
            return { browsers: server.browsers.map((b) => ({ ...b })) };
        },
    };
});

import { popOutItem } from './pop-out';
import { browsers } from './api.svelte';
import { openPages } from './pages.svelte';
import { browserFromSearch, browserPath, browserWindowName } from '../../popout/popout';

const ARTIFACT_ID = 'fedcba9876543210';
const APP_ID = 'aaaaaaaaaaaaaaaa';
const BROWSER_ID = '0123456789abcdef';

function fakeWindow() {
    const calls: unknown[][] = [];
    const tab = { opener: {} as unknown, location: { href: '' }, close: () => {} };
    const win = { open: (...args: unknown[]) => { calls.push(args); return args[2] === 'noopener' ? null : tab; }, __tab: tab };
    return { win: win as unknown as Window & { __tab: typeof tab }, calls };
}

beforeEach(() => {
    server.reads = 0;
    server.browsers = [];
    server.pages = [
        { id: ARTIFACT_ID, key: 'huddle_artifact:5:ab12cd34', frame: 'sandboxed', title: 'Layout A', opened_at: 1, src: '/api/v1/cplugs/huddle/artifact-view/fresh.sig' },
        { id: APP_ID, key: 'app:/static/popout.html?tab=flow', frame: 'app', title: 'flow', opened_at: 2, src: '/static/popout.html?tab=flow' },
    ];
});

describe('pop out', () => {
    test('an artifact opens a new tab at its freshly ticketed viewer path after a list read', async () => {
        const { win, calls } = fakeWindow();
        expect(await popOutItem(ARTIFACT_ID, win)).toBe(true);
        expect(server.reads).toBe(1);
        expect(calls[0]?.slice(0, 2)).toEqual(['about:blank', '_blank']);
        expect(calls[0]?.length).toBe(2);
        expect(win.__tab.location.href).toBe('/api/v1/cplugs/huddle/artifact-view/fresh.sig');
        expect(win.__tab.opener).toBeNull();
    });

    test('an app page opens a new tab at its same-origin path: _blank, noopener, NO features string, synchronously', async () => {
        await openPages.refresh(true);
        const { win, calls } = fakeWindow();
        const pending = popOutItem(APP_ID, win);
        expect(calls).toEqual([['/static/popout.html?tab=flow', '_blank', 'noopener']]);
        return expect(pending).resolves.toBe(true);
    });

    test('an id on neither list falls back to the browser pop-out page', async () => {
        server.pages = [];
        await openPages.refresh(true);
        const { win, calls } = fakeWindow();
        expect(await popOutItem(APP_ID, win)).toBe(true);
        expect(calls).toEqual([[`/static/popout.html?browser=${APP_ID}`, '_blank', 'noopener']]);
    });

    test.each([
        [{ frame: 'app', src: 'https://evil.example/static/popout.html' }],
        [{ frame: 'app', src: '/static/index.html' }],
        [{ frame: 'sandboxed', src: '/static/popout.html' }],
        [{ frame: 'sandboxed', src: null }],
    ])('a page that cannot be framed opens no window: %j', async (bad) => {
        server.pages = [{ id: APP_ID, key: 'k', title: 't', opened_at: 1, ...bad }];
        const { win, calls } = fakeWindow();
        expect(await popOutItem(APP_ID, win)).toBe(false);
        expect(calls).toEqual([]);
    });

    test('a remote browser opens a new tab at the address it is showing (its stored url)', async () => {
        server.browsers = [{ id: BROWSER_ID, label: 'b', url: 'https://example.com/docs', state: 'live', viewers: 0, created_at: '', updated_at: '' }];
        await browsers.refresh(true);
        const { win, calls } = fakeWindow();
        expect(await popOutItem(BROWSER_ID, win)).toBe(true);
        expect(calls).toEqual([['https://example.com/docs', '_blank', 'noopener']]);
    });

    test('a remote browser with no usable address falls back to its pop-out page in a tab', async () => {
        server.browsers = [{ id: BROWSER_ID, label: 'b', url: 'about:blank', state: 'live', viewers: 0, created_at: '', updated_at: '' }];
        await browsers.refresh(true);
        const { win, calls } = fakeWindow();
        expect(await popOutItem(BROWSER_ID, win)).toBe(true);
        expect(calls).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
    });

    test('inside the desktop app the artifact is fetched first (no blank tab) and the open goes external', async () => {
        const { win, calls } = fakeWindow();
        (win as unknown as { carnivoreDesktop: object }).carnivoreDesktop = {};
        expect(await popOutItem(ARTIFACT_ID, win)).toBe(true);
        expect(calls).toEqual([['/api/v1/cplugs/huddle/artifact-view/fresh.sig', '_blank', 'noopener']]);
    });

    test('a malformed id opens nothing and reads nothing', async () => {
        const { win, calls } = fakeWindow();
        expect(await popOutItem('../../x', win)).toBe(false);
        expect(calls).toEqual([]);
        expect(server.reads).toBe(0);
    });

    test('the pop-out page asks for a browser only by a well-formed id', () => {
        expect(browserFromSearch(`?browser=${BROWSER_ID}`)).toBe(BROWSER_ID);
        expect(browserFromSearch('?browser=../x')).toBeNull();
        expect(browserFromSearch('?tab=huddle')).toBeNull();
        expect(browserFromSearch(new URL(`http://x${browserPath(BROWSER_ID)}`).search)).toBe(BROWSER_ID);
        expect(browserWindowName(BROWSER_ID)).toBe(`carnivore-browser-${BROWSER_ID}`);
    });
});
