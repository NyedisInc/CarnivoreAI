/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

vi.hoisted(() => localStorage.setItem('claude_tunnel_token', 'an-access-token'));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string) => (p === '/browsers/pages' ? { pages: [] } : { browsers: [] }),
    };
});
vi.mock('./browser-socket', () => ({ openBrowserSocket: () => ({ send: () => {}, reopen: () => {}, close: () => {} }) }));
vi.mock('./pop-out', () => ({ popOutItem: async () => true }));

import { browserBridge, closeBrowserScreen, dismissBrowserScreen, openBrowser } from './screen-host';

const BROWSER_ID = '0123456789abcdef';

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

function fakeHideAllScreens(): void {
    document.querySelectorAll('.screen').forEach((el) => el.classList.remove('active'));
    closeBrowserScreen();
}

const headerCalls: string[] = [];

describe('the browser screen as a navigation', () => {
    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        document.body.innerHTML = '<span id="header-title-text" data-full-title="ses 02c3ff15">ses 02c3ff15</span>'
            + '<span id="header-rename-pencil"></span>'
            + '<div id="terminal-screen" class="screen active"><div id="terminal-grid"><div id="browser-screen"></div></div></div>';
        document.title = 'ses 02c3ff15 - Carnivore';
        headerCalls.length = 0;
        const g = globalThis as Record<string, unknown>;
        g.App = { hideAllScreens: fakeHideAllScreens };
        g.setHeaderIdentity = (o: { icon: string; title: string }) => { headerCalls.push(`${o.icon}:${o.title}`); };
        g.setPageTitle = (t: string | null) => { document.title = t ? `${t} - Carnivore` : 'Carnivore'; };
    });
    afterEach(() => {
        dismissBrowserScreen();
        for (const k of ['App', 'setHeaderIdentity', 'setPageTitle']) delete (globalThis as Record<string, unknown>)[k];
        document.body.innerHTML = '';
        history.replaceState(null, '', '/');
        vi.unstubAllGlobals();
    });

    const terminal = (): HTMLElement => document.getElementById('terminal-screen') as HTMLElement;

    test('opening a row parks the previous screen, and closing the screen restores it', async () => {
        expect(openBrowser(BROWSER_ID)).toBe(true);
        await settle();
        expect(document.querySelector('.bscreen')).not.toBeNull();
        expect(terminal().classList.contains('active')).toBe(true);
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(true);
        expect(document.querySelector('#terminal-grid > #browser-screen .bscreen')).not.toBeNull();
        expect(location.hash).toBe(`#browser/${BROWSER_ID}`);
        expect(headerCalls.at(-1)).toMatch(/^brand:.+/);
        expect(headerCalls.at(-1)).not.toContain('02c3ff15');
        expect(document.title).not.toContain('02c3ff15');

        expect(browserBridge.dismiss()).toBe(true);
        await settle();
        expect(document.querySelector('.bscreen')).toBeNull();
        expect(terminal().classList.contains('active')).toBe(true);
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(false);
        expect(location.hash).toBe('');
        expect(headerCalls.at(-1)).toBe('cloude:ses 02c3ff15');
        expect(document.title).toBe('ses 02c3ff15 - Carnivore');
    });

    test('another navigation takes the browser screen down and does not restore the old screen', async () => {
        openBrowser(BROWSER_ID);
        await settle();
        fakeHideAllScreens();
        await settle();
        expect(document.querySelector('.bscreen')).toBeNull();
        expect(terminal().classList.contains('active')).toBe(false);
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(false);
    });

    test('opened from a screen that is not the session screen, it raises the session screen and a dismiss lowers it', async () => {
        document.body.insertAdjacentHTML('beforeend', '<div id="launchpad-screen" class="screen active"></div>');
        terminal().classList.remove('active');
        const home = document.getElementById('launchpad-screen')!;
        openBrowser(BROWSER_ID);
        await settle();
        expect(home.classList.contains('active')).toBe(false);
        expect(terminal().classList.contains('active')).toBe(true);
        dismissBrowserScreen();
        await settle();
        expect(terminal().classList.contains('active')).toBe(false);
        expect(home.classList.contains('active')).toBe(true);
    });
});
