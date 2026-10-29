/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { ThemeManifest } from '../../opscenter/api';

const { MANIFESTS, openThemes } = vi.hoisted(() => ({
    openThemes: vi.fn(),
    MANIFESTS: [
        { id: 'zed', name: 'Zed', description: '', author: null, version: null, source: 'user', cssVars: { '--color-accent': '#123456' }, xterm: {} },
        {
            id: 'carnivore', name: 'Carnivore', description: '', author: null, version: null, source: 'builtin',
            cssVars: { '--color-bg-page': '#02161e', '--color-accent': '#ff4652', '--color-fg': '#cbd6d9' }, xterm: {},
        },
        { id: 'dracula', name: 'Dracula', description: '', author: null, version: null, source: 'builtin', cssVars: { '--color-accent': '#bd93f9' }, xterm: {} },
    ] as ThemeManifest[],
}));

vi.mock('../../opscenter/api', () => ({
    themes: { status: 'ok', data: MANIFESTS, error: null, fetchedAt: 0, refresh: () => Promise.resolve(), stop() {} },
    openThemes,
}));

import ThemePicker from './ThemePicker.svelte';
import { themeFavorites } from '../themes-page/favorites.svelte';
import { RECENT_THEMES_KEY } from '../themes-page/global-theme';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
themeFavorites.start();

const applyTheme = vi.fn(() => true);
let active = 'carnivore';

beforeEach(() => {
    applyTheme.mockClear();
    openThemes.mockClear();
    active = 'carnivore';
    localStorage.clear();
    themeFavorites.ids = [];
    (globalThis as { Themes?: unknown }).Themes = { applyTheme, getActiveGlobal: () => ({ id: active }), DEFAULT_THEME_ID: 'carnivore' };
});

afterEach(() => {
    delete (globalThis as { Themes?: unknown }).Themes;
    document.body.innerHTML = '';
});

function render(): { target: HTMLElement; handle: Record<string, unknown> } {
    const target = document.createElement('div');
    document.body.append(target);
    const handle = mount(ThemePicker, { target, props: {} }) as Record<string, unknown>;
    flushSync();
    return { target, handle };
}

test('shows the current theme and, as quick choices, favorites first then recents, never the current one', () => {
    localStorage.setItem(RECENT_THEMES_KEY, JSON.stringify(['dracula', 'carnivore']));
    themeFavorites.ids = ['zed'];
    const { target, handle } = render();
    expect(target.querySelector('[data-testid="theme-current"]')!.textContent).toBe('Carnivore');
    expect([...target.querySelectorAll<HTMLElement>('[data-theme-id]')].map((c) => c.dataset.themeId)).toEqual(['zed', 'dracula']);
    unmount(handle);
});

test('a swatch is painted in the theme\'s OWN colours, never the page\'s', () => {
    themeFavorites.ids = ['dracula'];
    const { target, handle } = render();
    expect(target.querySelector<HTMLElement>('[data-theme-id="dracula"] .tp__sw')!.getAttribute('style')).toMatch(/--p-accent:\s*#bd93f9/);
    unmount(handle);
});

test('a quick choice switches the global theme through the shared writer and shows it current', () => {
    themeFavorites.ids = ['dracula'];
    const { target, handle } = render();
    target.querySelector<HTMLElement>('[data-theme-id="dracula"]')!.click();
    flushSync();
    expect(applyTheme).toHaveBeenCalledExactlyOnceWith('dracula', { persist: true });
    expect(target.querySelector('[data-testid="theme-current"]')!.textContent).toBe('Dracula');
    expect(JSON.parse(localStorage.getItem(RECENT_THEMES_KEY)!)).toEqual(['dracula']);
    unmount(handle);
});

test('browse all themes opens the themes page', () => {
    const { target, handle } = render();
    target.querySelector<HTMLElement>('[data-theme-browse]')!.click();
    expect(openThemes).toHaveBeenCalledOnce();
    unmount(handle);
});
