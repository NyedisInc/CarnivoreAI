
import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import ThemesScreen from './ThemesScreen.svelte';
import type { Component } from 'svelte';

export const THEMES_SCREEN_CONTAINER = 'themes-screen';

export const THEMES_HASH = '#themes';

const THEMES_SCREEN_PANEL = ThemesScreen as unknown as Component<
    Record<string, never>,
    Record<string, unknown>
>;

interface ScreenHandle {
    show?: () => void;
    close?: () => void;
    isOpen?: () => boolean;
}

export function mountThemesScreen(): Record<string, unknown> | null {
    return ensurePanel(THEMES_SCREEN_CONTAINER, THEMES_SCREEN_PANEL, {});
}

export function unmountThemesScreen(): boolean {
    return unmountPanel(THEMES_SCREEN_CONTAINER);
}

export function openThemesScreen(): boolean {
    const handle = (mountThemesScreen() ?? panelInstance(THEMES_SCREEN_CONTAINER)) as ScreenHandle | null;
    if (!handle || typeof handle.show !== 'function') return false;
    handle.show();
    return true;
}

export function closeThemesScreen(): boolean {
    const handle = panelInstance(THEMES_SCREEN_CONTAINER) as ScreenHandle | null;
    if (!handle || typeof handle.close !== 'function') return false;
    handle.close();
    return true;
}

export function isThemesHash(hash: string | null | undefined): boolean {
    if (typeof hash !== 'string') return false;
    const trimmed = hash.trim();
    if (!trimmed) return false;
    const bare = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed;
    return bare === THEMES_HASH.slice(1);
}

export function wireThemesDeepLink(
    target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
    if (!target) return () => {};
    const apply = (): void => {
        if (isThemesHash(target.location?.hash)) openThemesScreen();
        else closeThemesScreen();
    };
    target.addEventListener('hashchange', apply);
    const stopWaiting = whenLegacyBootComplete(target, apply);
    return () => {
        stopWaiting();
        target.removeEventListener('hashchange', apply);
    };
}
