/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { ThemeManifest } from '../../opscenter/api';

const { MANIFESTS, refresh, openCatalogScreen } = vi.hoisted(() => ({
    refresh: vi.fn(async () => {}),
    openCatalogScreen: vi.fn(() => true),
    MANIFESTS: [
    {
        id: 'rogue', name: 'Rogue', description: 'user made', author: 'someone', version: '1.0', source: 'user',
        cssVars: { '--color-bg-page': '#111111', '--color-accent': 'url(javascript:alert(1))' },
        xterm: { background: '#222222', cursor: '#abcdef' },
    },
    {
        id: 'matrix', name: 'Matrix', description: 'green rain', author: null, version: null, source: 'builtin',
        cssVars: { '--color-bg-page': '#000800', '--color-accent': '#00ff41', '--ascii-display': 'block' },
        xterm: { background: '#000000' }, effects: 'effects.js',
    },
    ] as ThemeManifest[],
}));

vi.mock('../../opscenter/api', () => ({
    themes: { status: 'ok', data: MANIFESTS, error: null, fetchedAt: 0, refresh: (...args: unknown[]) => refresh(...(args as [])), stop() {} },
}));
vi.mock('../catalog/screen-host', () => ({ openCatalogScreen: (...args: unknown[]) => openCatalogScreen(...(args as [])) }));

import { mount, unmount } from 'svelte';
import ThemesScreen from './ThemesScreen.svelte';
import { themeFavorites } from './favorites.svelte';

let target: HTMLElement;
let app: Record<string, unknown> | null = null;

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function start(focusId: string | null = null): void {
    app = mount(ThemesScreen, { target, props: { embedded: true, focusId } });
}

beforeEach(async () => {
    target = document.createElement('div');
    document.body.appendChild(target);
    document.documentElement.dataset.theme = 'matrix';
    themeFavorites.ids = [];
});

afterEach(() => {
    if (app) void unmount(app);
    app = null;
    document.body.innerHTML = '';
});

describe('the embedded themes page', () => {
    test('arrives with no detail panel and no selected card, a click opens it and close drops it', async () => {
        start();
        await settle();
        expect(document.querySelector('[data-inspector]')).toBeNull();
        expect(document.querySelector('.themes-side')).toBeNull();
        (document.querySelector('[data-theme-card="rogue"] .catalog-card__open') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('rogue');
        (document.querySelector('[data-themes-back]') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('.themes-side')).toBeNull();
    });

    test('a focusId deep link opens that theme', async () => {
        start('rogue');
        await settle();
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('rogue');
    });
});
