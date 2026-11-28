import { flushSync, type Component } from 'svelte';
import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import { closeMenuPagesExcept, syncMenuPages } from '../menu-page/menu-page-shell.svelte';
import { MENU_PAGES } from '../menu-page/menu-pages';

interface ScreenHandle {
    show?: (options?: Record<string, unknown>) => void;
    close?: () => void;
    isOpen?: () => boolean;
}

export interface OverlayHost {
    mount(): Record<string, unknown> | null;
    unmount(): boolean;
    open(options?: Record<string, unknown>): boolean;
    close(): boolean;
    isHash(hash: string | null | undefined): boolean;
    wireDeepLink(target?: Window | null): () => void;
}

/* the fragment that opens it */
export interface LazyOverlayComponent {
    load: () => Promise<{ default: Component<Record<string, never>, Record<string, unknown>> | Component<Record<string, never>> }>;
}

function isLazyComponent(
    value: Component<Record<string, never>, Record<string, unknown>> | Component<Record<string, never>> | LazyOverlayComponent,
): value is LazyOverlayComponent {
    return typeof value === 'object' && value !== null && typeof (value as LazyOverlayComponent).load === 'function';
}

export function createOverlayHost(
    containerId: string,
    component: Component<Record<string, never>, Record<string, unknown>> | Component<Record<string, never>> | LazyOverlayComponent,
    hash: string,
    options: { aliases?: readonly string[]; props?: Record<string, unknown> } = {},
): OverlayHost {
    let loadedPanel: Component<Record<string, never>, Record<string, unknown>> | null = isLazyComponent(component)
        ? null
        : (component as unknown as Component<Record<string, never>, Record<string, unknown>>);
    let loadPromise: Promise<Component<Record<string, never>, Record<string, unknown>> | null> | null = null;
    let pendingOpen: { options?: Record<string, unknown> } | null = null;

    const name = hash.replace(/^#/, '');
    const names = [name, ...(options.aliases ?? []).map((alias) => alias.replace(/^#/, ''))];

    function hasContainer(): boolean {
        return typeof document !== 'undefined' && typeof document.getElementById === 'function' && document.getElementById(containerId) !== null;
    }

    function ensureLoaded(): Promise<Component<Record<string, never>, Record<string, unknown>> | null> {
        if (loadedPanel) return Promise.resolve(loadedPanel);
        if (!isLazyComponent(component)) return Promise.resolve(null);
        loadPromise ??= component.load().then((mod) => {
            loadedPanel = mod.default as unknown as Component<Record<string, never>, Record<string, unknown>>;
            return loadedPanel;
        }).catch((err) => {
            loadPromise = null;
            console.error(`overlay-host: failed to load ${containerId}`, err);
            return null;
        });
        return loadPromise;
    }

    function mount(): Record<string, unknown> | null {
        if (!loadedPanel) {
            void ensureLoaded();
            return panelInstance(containerId);
        }
        return ensurePanel(containerId, loadedPanel, (options.props ?? {}) as Record<string, never>);
    }

    const pageId = MENU_PAGES.find((p) => p.containerId === containerId)?.id ?? null;

    function openLoaded(openOptions?: Record<string, unknown>): boolean {
        const handle = (mount() ?? panelInstance(containerId)) as ScreenHandle | null;
        if (!handle || typeof handle.show !== 'function') return false;
        flushSync(() => handle.show?.(openOptions));
        syncMenuPages();
        return true;
    }

    function open(openOptions?: Record<string, unknown>): boolean {
        if (pageId) closeMenuPagesExcept(pageId);
        if (loadedPanel) return openLoaded(openOptions);
        if (!hasContainer()) return false;
        const ticket = { options: openOptions };
        pendingOpen = ticket;
        void ensureLoaded().then((panel) => {
            if (!panel || pendingOpen !== ticket) return;
            pendingOpen = null;
            openLoaded(ticket.options);
        });
        return true;
    }

    function close(): boolean {
        if (pendingOpen) {
            pendingOpen = null;
            return true;
        }
        const handle = panelInstance(containerId) as ScreenHandle | null;
        if (!handle || typeof handle.close !== 'function') return false;
        flushSync(() => handle.close?.());
        syncMenuPages();
        return true;
    }

    function isHash(value: string | null | undefined): boolean {
        if (typeof value !== 'string') return false;
        const trimmed = value.trim();
        const bare = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed;
        return names.some((n) => bare === n || bare.startsWith(`${n}/`));
    }

    function wireDeepLink(target: Window | null = typeof window !== 'undefined' ? window : null): () => void {
        if (!target) return () => {};
        let wasOurs = false;
        const apply = (): void => {
            const ours = isHash(target.location?.hash);
            if (ours) open();
            else if (wasOurs) close();
            wasOurs = ours;
        };
        target.addEventListener('hashchange', apply);
        const stopWaiting = whenLegacyBootComplete(target, apply);
        return () => {
            stopWaiting();
            target.removeEventListener('hashchange', apply);
        };
    }

    return { mount, unmount: () => unmountPanel(containerId), open, close, isHash, wireDeepLink };
}
