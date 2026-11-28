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

vi.mock('../../plugins-page/cplugs-adapter', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../plugins-page/cplugs-adapter')>();
    return {
        ...actual,
        createCplugsAdapter: () => ({
            list: async () => [
                {
                    id: 'cplug:devlab',
                    cplugId: 'devlab',
                    name: 'Dev Lab',
                    description: 'dev feature',
                    tier: 'dev',
                    runtime: 'sidecar',
                    enabled: true,
                    state: 'active',
                    thirdParty: false,
                    unverified: false,
                    permissions: [],
                    surfaces: {},
                    settings: {},
                    settingsSchema: { version: 1, fields: {} },
                    revision: 1,
                },
                {
                    id: 'cplug:clock',
                    cplugId: 'clock',
                    name: 'Clock',
                    description: 'catalog plugin',
                    tier: 'catalog',
                    runtime: 'sidecar',
                    enabled: true,
                    state: 'active',
                    thirdParty: true,
                    unverified: false,
                    permissions: [],
                    surfaces: {},
                    settings: {},
                    settingsSchema: { version: 1, fields: {} },
                    revision: 1,
                },
            ],
            toggle: async () => {},
            update: async () => {},
        }),
    };
});

vi.mock('../../plugins-page/catalog-plugins.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../plugins-page/catalog-plugins.svelte')>();
    return {
        ...actual,
        createCatalogPlugins: () => ({
            items: () => [],
            projects: [],
            loadError: null,
            load: async () => {},
        }),
    };
});

vi.mock('../../plugins-page/sideload-store.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../plugins-page/sideload-store.svelte')>();
    const fakeApi = {
        load: async () => ({ enabled: false, expires_at: null, hours: 12, items: [] }),
        save: async () => ({ enabled: false, expires_at: null, hours: 12, items: [] }),
        folder: async () => ({}),
        git: async () => ({}),
        resync: async () => ({}),
        remove: async () => ({}),
    };
    return {
        ...actual,
        createSideloadStore: () => actual.createSideloadStore(fakeApi),
    };
});

vi.mock('../../plugins-page/plugin-health.svelte', () => ({
    createPluginHealth: () => ({
        report: null,
        loading: false,
        error: null,
        load: async () => {},
    }),
}));

import ThemesScreen from '../../themes-page/ThemesScreen.svelte';
import InstalledPage from './InstalledPage.svelte';
import type { MenuNode } from './route';
import type { MenuSources } from './model';

const SOURCES: MenuSources = {
    storeTotal: 0, storeNewest: 0, storeUpdates: 0, storeByKind: { skill: 0, theme: 2, mod: 0, plugin: 0, widget: 0, loadout: 0 }, storeItems: [],
    installed: { skill: [], theme: [{ key: 'rogue', title: 'Rogue', word: '' }, { key: 'matrix', title: 'Matrix', word: 'global' }], mod: [], plugin: [], widget: [], loadout: [] },
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

    test('INSTALLED > plugins passes scope="plugins" to PluginsScreen, filtering out dev feature-tier items', async () => {
        const host = show({ scope: 'installed', page: 'kind', kind: 'plugin' });
        await new Promise((r) => setTimeout(r, 10));
        flushSync();
        expect(host.querySelector('[data-installed-screen="plugin"]')).not.toBeNull();
        const text = host.textContent ?? '';
        expect(text).toContain('Clock');
        expect(text).not.toContain('Dev Lab');
    });
});
