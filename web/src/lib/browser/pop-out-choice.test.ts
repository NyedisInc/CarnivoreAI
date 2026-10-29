/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return { browsers: [] as Record<string, unknown>[], pages: [] as Record<string, unknown>[] };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string) =>
            p === '/browsers/pages' ? { pages: server.pages.map((x) => ({ ...x })) } : { browsers: server.browsers.map((x) => ({ ...x })) },
    };
});
vi.mock('./browser-socket', () => ({ openBrowserSocket: () => ({ send: () => {}, reopen: () => {}, close: () => {} }) }));

import { t } from '../i18n/index.svelte';
import { browsers } from './api.svelte';
import { openPages } from './pages.svelte';
import { askProxyPopOut } from './pop-out-choice';
import { browserBridge } from './screen-host';

const BROWSER_ID = '0123456789abcdef';
const PAGE_ID = 'aaaaaaaaaaaaaaaa';

function proxyBrowser(url: string): Record<string, unknown> {
    return { id: BROWSER_ID, label: 'docs', url, state: 'live', viewers: 0, created_at: '', updated_at: '' };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

const dialog = (): HTMLElement | null => document.querySelector('.modal-overlay');
const choice = (which: 'proxy' | 'real'): HTMLButtonElement => document.querySelector(`[data-popout-choice="${which}"]`)!;

let opened: unknown[][];

beforeEach(async () => {
    opened = [];
    vi.spyOn(window, 'open').mockImplementation((...args: unknown[]) => { opened.push(args); return null; });
    server.browsers = [proxyBrowser('https://example.com/docs')];
    server.pages = [{ id: PAGE_ID, key: 'app:/static/popout.html?tab=flow', frame: 'app', title: 'flow', opened_at: 1, src: '/static/popout.html?tab=flow' }];
    await browsers.refresh(true);
    await openPages.refresh(true);
});

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

describe('pop out of a proxy browser asks every time', () => {
    test('the drawer\'s pop out asks first and opens nothing until a choice; "pop out the proxy" opens the proxy page in the click', async () => {
        const pending = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(dialog()).not.toBeNull();
        expect(opened).toEqual([]);
        choice('proxy').click();
        expect(opened).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
        await expect(pending).resolves.toBe(true);
        expect(dialog()).toBeNull();

        const again = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(dialog()).not.toBeNull();
        choice('real').click();
        expect(opened[1]).toEqual(['https://example.com/docs', '_blank', 'noopener']);
        await expect(again).resolves.toBe(true);
    });

    test('Escape cancels and so does cancel: nothing opens and the bridge answers false', async () => {
        const viaEscape = browserBridge.popOut(BROWSER_ID);
        await settle();
        dialog()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await expect(viaEscape).resolves.toBe(false);

        const viaCancel = browserBridge.popOut(BROWSER_ID);
        await settle();
        document.querySelector<HTMLButtonElement>('[data-popout-cancel]')!.click();
        await expect(viaCancel).resolves.toBe(false);
        expect(opened).toEqual([]);
        expect(dialog()).toBeNull();
    });

    test('Enter takes the focused choice: the proxy has focus at open, and Enter on the real choice opens the real page', async () => {
        const first = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(document.activeElement).toBe(choice('proxy'));
        const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        choice('proxy').dispatchEvent(enter);
        expect(enter.defaultPrevented).toBe(true);
        expect(opened).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
        await expect(first).resolves.toBe(true);

        const second = browserBridge.popOut(BROWSER_ID);
        await settle();
        choice('real').focus();
        choice('real').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(opened[1]).toEqual(['https://example.com/docs', '_blank', 'noopener']);
        await expect(second).resolves.toBe(true);
    });

    test('a page row does not ask: it opens its own path directly', async () => {
        expect(await browserBridge.popOut(PAGE_ID)).toBe(true);
        expect(dialog()).toBeNull();
        expect(opened).toEqual([['/static/popout.html?tab=flow', '_blank', 'noopener']]);
    });

    test('a loopback address off the host cannot be opened for real; the proxy still can', async () => {
        const off = { open: (...args: unknown[]) => { opened.push(args); return null; }, location: { hostname: 'carnivore.lan' } };
        const pending = askProxyPopOut({ id: BROWSER_ID, label: 'dev', url: 'http://localhost:3000/' }, null, off as unknown as Window);
        await settle();
        expect(choice('real').disabled).toBe(true);
        expect(document.querySelector('[data-popout-real-hint]')!.textContent).toBe(t('browser.popout.host_only'));
        choice('real').click();
        expect(opened).toEqual([]);
        choice('proxy').click();
        expect(opened).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
        await expect(pending).resolves.toBe('proxy');
    });

    test('the live address wins over the stored, shortened one, and only the stored one says so', async () => {
        const live = askProxyPopOut({ id: BROWSER_ID, label: 'docs', url: 'https://example.com/docs' }, 'https://example.com/docs?page=2#top');
        await settle();
        expect(document.querySelector('[data-popout-shortened]')).toBeNull();
        choice('real').click();
        expect(opened).toEqual([['https://example.com/docs?page=2#top', '_blank', 'noopener']]);
        await live;

        const stored = askProxyPopOut({ id: BROWSER_ID, label: 'docs', url: 'https://example.com/docs' }, null);
        await settle();
        expect(document.querySelector('[data-popout-shortened]')).not.toBeNull();
        choice('proxy').click();
        await stored;
    });

    test('a blank proxy browser still asks, with the real page off for want of an address', async () => {
        const pending = askProxyPopOut({ id: BROWSER_ID, label: 'blank', url: 'about:blank' }, null);
        await settle();
        expect(choice('real').disabled).toBe(true);
        expect(document.querySelector('[data-popout-real-hint]')!.textContent).toBe(t('browser.popout.no_address'));
        choice('proxy').click();
        await expect(pending).resolves.toBe('proxy');
    });
});

describe('every proxy browser pop out asks, once at a time', () => {
    test('a proxy browser the held list does not carry yet is read fresh and still asks', async () => {
        server.browsers = [];
        await browsers.refresh(true);
        server.browsers = [proxyBrowser('https://example.com/new')];
        const pending = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(dialog()).not.toBeNull();
        expect(opened).toEqual([]);
        choice('real').click();
        expect(opened).toEqual([['https://example.com/new', '_blank', 'noopener']]);
        await expect(pending).resolves.toBe(true);
    });

    test('an id neither list carries after a fresh read still asks, as a proxy browser with no address', async () => {
        server.browsers = [];
        await browsers.refresh(true);
        const pending = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(dialog()).not.toBeNull();
        expect(choice('real').disabled).toBe(true);
        expect(document.querySelector('.modal-overlay')!.textContent).toContain(t('browser.popout.title', { label: t('browser.page') }));
        choice('proxy').click();
        expect(opened).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
        await expect(pending).resolves.toBe(true);
    });

    test('two pop outs back to back show one dialog, and one choice opens one tab', async () => {
        const first = browserBridge.popOut(BROWSER_ID);
        const second = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(document.querySelectorAll('.modal-overlay')).toHaveLength(1);
        choice('proxy').click();
        await expect(first).resolves.toBe(true);
        await expect(second).resolves.toBe(true);
        await settle();
        expect(opened).toEqual([[`/static/popout.html?browser=${BROWSER_ID}`, '_blank', 'noopener']]);
        expect(dialog()).toBeNull();

        const third = browserBridge.popOut(BROWSER_ID);
        await settle();
        expect(document.querySelectorAll('.modal-overlay')).toHaveLength(1);
        document.querySelector<HTMLButtonElement>('[data-popout-cancel]')!.click();
        await expect(third).resolves.toBe(false);
    });
});

describe('the kind is named proxy browser', () => {
    test('the row label, the screen label, the close item and the open menu say "proxy browser"; the list heading stays "browsers"', () => {
        expect(t('browser.row.live')).toBe('proxy browser, running');
        expect(t('browser.row.stopped').startsWith('proxy browser, stopped')).toBe(true);
        expect(t('browser.screen', { label: 'docs' })).toBe('proxy browser: docs');
        expect(t('browser.menu.close')).toBe('close proxy browser');
        expect(t('browser.close.confirm')).toBe('close this proxy browser?');
        expect(t('drawer.new.browser')).toBe('proxy browser');
        expect(t('opscenter.cell.browser.title')).toBe('proxy browser');
        expect(t('browser.section')).toBe('browsers');
        expect(t('drawer.rail.browsers')).toBe('browsers');
        expect(t('browser.row.page')).not.toContain('proxy');
        expect(t('browser.screen.page', { label: 'flow' })).toBe('page: flow');
    });
});
