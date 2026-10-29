/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import type { ThemeManifest } from '../../../opscenter/api';

const { MANIFESTS } = vi.hoisted(() => ({
    MANIFESTS: [
        { id: 'rogue', name: 'Rogue', description: 'user made', author: 'someone', version: '1.0', source: 'user', cssVars: { '--color-bg-page': '#111111' }, xterm: { background: '#222222' } },
        { id: 'matrix', name: 'Matrix', description: 'green rain', author: null, version: null, source: 'builtin', cssVars: { '--color-bg-page': '#000800' }, xterm: { background: '#000000' } },
    ] as ThemeManifest[],
}));

vi.mock('../../../opscenter/api', () => ({
    themes: { status: 'ok', data: MANIFESTS, error: null, fetchedAt: 0, refresh: async () => {}, stop() {} },
}));

import ThemesScreen from '../../themes-page/ThemesScreen.svelte';
import InstalledPage from './InstalledPage.svelte';
import type { MenuNode } from './route';
import type { MenuSources } from './model';

const SOURCES: MenuSources = {
    storeTotal: 0, storeNewest: 0, storeUpdates: 0, storeByKind: { skill: 0, theme: 2, mod: 0, plugin: 0 }, storeItems: [],
    installed: { skill: [], theme: [{ key: 'rogue', title: 'Rogue', word: '' }, { key: 'matrix', title: 'Matrix', word: 'global' }], mod: [], plugin: [] },
    flagged: [], needs: [],
};
const t = (key: string) => key;

let mounted: Record<string, unknown> | null = null;

function show(node: MenuNode, onNavigate = vi.fn()): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    mounted = mount(InstalledPage, { target: host, props: { node: node as never, sources: SOURCES, t: t as never, onNavigate } });
    flushSync();
    return host;
}

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

describe('an installed node is the kind\'s real page', () => {
    test('INSTALLED > themes mounts the Themes screen: cards, filter chips, search, no second title bar', () => {
        const host = show({ scope: 'installed', page: 'kind', kind: 'theme' });
        expect(host.querySelector('[data-installed-screen="theme"] .themes-screen')).not.toBeNull();
        expect([...host.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim())).toEqual(['Rogue']);
        expect(host.querySelectorAll('[data-theme-filter]').length).toBeGreaterThanOrEqual(3);
        expect([...host.querySelectorAll('[data-theme-filter]')].some((c) => /built in/.test(c.textContent ?? ''))).toBe(false);
        expect(host.querySelector('.oc-titlebar')).toBeNull();
        expect(host.querySelector('[data-installed-page]')).toBeNull();
    });

    test('the standalone Themes screen (no storeOnly) still lists the built-in theme beside the user one', () => {
        const host = document.createElement('div');
        document.body.appendChild(host);
        mounted = mount(ThemesScreen, { target: host, props: { embedded: true } });
        flushSync();
        expect([...host.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim())).toEqual(['Matrix', 'Rogue']);
        expect([...host.querySelectorAll('[data-theme-filter]')].some((c) => /built in/.test(c.textContent ?? ''))).toBe(true);
    });

    test('a theme item node opens that theme in the Themes inspector', () => {
        const host = show({ scope: 'installed', page: 'item', kind: 'theme', key: 'rogue' });
        expect(host.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('rogue');
        expect(host.querySelector('[data-theme-card="rogue"] .catalog-card')?.getAttribute('aria-current')).toBe('true');
    });

    test('"library" goes to the kind\'s store node in the same page', () => {
        const onNavigate = vi.fn();
        const host = show({ scope: 'installed', page: 'kind', kind: 'theme' }, onNavigate);
        const library = [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'get more on warez');
        library?.click();
        expect(onNavigate).toHaveBeenCalledWith({ scope: 'store', page: 'kind', kind: 'theme' });
    });

    test('picking a theme card inside the page reports the item node, so the address and the menu highlight follow', () => {
        const onNavigate = vi.fn();
        const host = show({ scope: 'installed', page: 'kind', kind: 'theme' }, onNavigate);
        host.querySelector<HTMLElement>('[data-theme-card="rogue"] .catalog-card__open')?.click();
        flushSync();
        expect(onNavigate).toHaveBeenCalledWith({ scope: 'installed', page: 'item', kind: 'theme', key: 'rogue' });
    });
});
