
import { ensurePanel, panelInstance } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import { t } from '../i18n/index.svelte';
import { BROWSER_ID, browserById, browsers, closeBrowser, createBrowser, renameBrowser, type BrowserInfo } from './api.svelte';
import type { PageInfo } from './page-frame';
import { closePage, openPages, pageById } from './pages.svelte';
import { popOutItem } from './pop-out';
import { askProxyPopOut } from './pop-out-choice';
import BrowserScreen from './BrowserScreen.svelte';
import { dropParkedScreens, occupyMainSection, parkCenterScreens, restoreParkedScreens, setBrowserHeader } from './center-nav';
import { reselectDrawer } from './drawer-repaint';
import { fileById } from '../open-files/api.svelte';
import { closeFileRow } from '../open-files/open-bridge';
import { registerMainAreaLayer } from '../sidebar-widgets/main-area-layers';
import type { Component } from 'svelte';

export const BROWSER_SCREEN_CONTAINER = 'browser-screen';

export const BROWSER_HASH_PREFIX = '#browser/';

const BROWSER_SCREEN_PANEL = BrowserScreen as unknown as Component<
    { onDismiss: () => void; onTitle: (title: string) => void },
    Record<string, unknown>
>;

interface ScreenHandle {
    show?: (id: string) => void;
    close?: () => void;
    showing?: () => string | null;
    currentUrl?: () => string | null;
}

export function browserIdFromHash(hash: string | null | undefined): string | null {
    if (typeof hash !== 'string' || !hash.startsWith(BROWSER_HASH_PREFIX)) return null;
    const id = hash.slice(BROWSER_HASH_PREFIX.length);
    return BROWSER_ID.test(id) ? id : null;
}

function handle(): ScreenHandle | null {
    return (ensurePanel(BROWSER_SCREEN_CONTAINER, BROWSER_SCREEN_PANEL, { onDismiss: dismissBrowserScreen, onTitle: setBrowserHeader })
        ?? panelInstance(BROWSER_SCREEN_CONTAINER)) as ScreenHandle | null;
}

function clearHash(): void {
    if (browserIdFromHash(location.hash) === null) return;
    history.replaceState(history.state, '', location.pathname + location.search);
}

export function openBrowserScreen(id: string): boolean {
    if (!BROWSER_ID.test(id)) return false;
    const screen = handle();
    if (!screen || typeof screen.show !== 'function') return false;
    if ((screen.showing?.() ?? null) === null) parkCenterScreens();
    occupyMainSection();
    screen.show(id);
    reselectDrawer();
    return true;
}

export function closeBrowserScreen(): boolean {
    const screen = panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null;
    dropParkedScreens();
    if (!screen || typeof screen.close !== 'function') return false;
    const was = screen.showing?.() ?? null;
    screen.close();
    clearHash();
    if (was !== null) reselectDrawer();
    return was !== null;
}

export function dismissBrowserScreen(): boolean {
    const screen = panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null;
    if (!screen || (screen.showing?.() ?? null) === null) return false;
    screen.close?.();
    clearHash();
    restoreParkedScreens();
    reselectDrawer();
    return true;
}

export function openBrowser(id: string): boolean {
    if (!BROWSER_ID.test(id)) return false;
    const opened = openBrowserScreen(id);
    if (browserIdFromHash(location.hash) !== id) {
        history.pushState(history.state, '', `${location.pathname}${location.search}${BROWSER_HASH_PREFIX}${id}`);
    }
    return opened;
}

export async function newBrowser(): Promise<boolean> {
    try {
        const made = await createBrowser();
        return openBrowser(made.id);
    } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        console.error('newBrowser: create refused', err);
        globalThis.alert?.(t('browser.create_failed', { detail }));
        return false;
    }
}

export function wireBrowserDeepLink(
    target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
    if (!target) return () => {};
    const apply = (): void => {
        const id = browserIdFromHash(target.location?.hash);
        if (id) openBrowserScreen(id);
        else dismissBrowserScreen();
    };
    target.addEventListener('hashchange', apply);
    const stopWaiting = whenLegacyBootComplete(target, apply);
    return () => {
        stopWaiting();
        target.removeEventListener('hashchange', apply);
    };
}

async function proxyBrowserFor(id: string): Promise<Pick<BrowserInfo, 'id' | 'label' | 'url'> | null> {
    if (pageById(id)) return null;
    const held = browserById(id);
    if (held) return held;
    const reads = await Promise.allSettled([browsers.refresh(true), openPages.refresh(true)]);
    for (const read of reads) {
        if (read.status === 'rejected') console.warn('pop out: list refresh failed', read.reason);
    }
    if (pageById(id)) return null;
    return browserById(id) ?? { id, label: '', url: '' };
}

export const browserBridge = {
    list: (): BrowserInfo[] => browsers.data ?? [],
    pages: (): PageInfo[] => openPages.data ?? [],
    open: openBrowser,
    showing: (): string | null => (panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null)?.showing?.() ?? null,
    dismiss: dismissBrowserScreen,
    rename: (id: string, label: string): Promise<BrowserInfo> =>
        fileById(id) ? Promise.reject(new Error(t('files.row.rename_locked')))
            : pageById(id) ? Promise.reject(new Error(t('browser.page.rename_locked'))) : renameBrowser(id, label),
    close: async (id: string): Promise<void> => {
        if (fileById(id)) {
            await closeFileRow(id);
            return;
        }
        if (pageById(id)) await closePage(id);
        else await closeBrowser(id);
        const screen = panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null;
        if (screen?.showing?.() === id) dismissBrowserScreen();
    },
    popOut: async (id: string): Promise<boolean> => {
        if (!BROWSER_ID.test(id) || fileById(id)) return false;
        const screen = (): ScreenHandle | null => panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null;
        const browser = await proxyBrowserFor(id);
        const opened = browser
            ? (await askProxyPopOut(browser, screen()?.showing?.() === id ? (screen()?.currentUrl?.() ?? null) : null)) !== null
            : await popOutItem(id);
        if (opened && screen()?.showing?.() === id) dismissBrowserScreen();
        return opened;
    },
};

registerMainAreaLayer({
    origin: 'sidebar',
    open: () => {
        const id = (panelInstance(BROWSER_SCREEN_CONTAINER) as ScreenHandle | null)?.showing?.() ?? null;
        return id !== null && fileById(id) != null;
    },
    close: () => void dismissBrowserScreen(),
});
