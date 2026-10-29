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

export function createOverlayHost(
    containerId: string,
    component: Component<Record<string, never>, Record<string, unknown>> | Component<Record<string, never>>,
    hash: string,
    options: { aliases?: readonly string[] } = {},
): OverlayHost {
    const panel = component as unknown as Component<Record<string, never>, Record<string, unknown>>;
    const name = hash.replace(/^#/, '');
    const names = [name, ...(options.aliases ?? []).map((alias) => alias.replace(/^#/, ''))];

    function mount(): Record<string, unknown> | null {
        return ensurePanel(containerId, panel, {});
    }

    const pageId = MENU_PAGES.find((p) => p.containerId === containerId)?.id ?? null;

    function open(options?: Record<string, unknown>): boolean {
        if (pageId) closeMenuPagesExcept(pageId);
        const handle = (mount() ?? panelInstance(containerId)) as ScreenHandle | null;
        if (!handle || typeof handle.show !== 'function') return false;
        flushSync(() => handle.show?.(options));
        syncMenuPages();
        return true;
    }

    function close(): boolean {
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
