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

import { closeThemesScreen, isThemesHash, openThemesScreen, THEMES_SCREEN_CONTAINER, unmountThemesScreen } from './screen-host';
import { themeFavorites } from './favorites.svelte';

const applyTheme = vi.fn(() => true);

function settle(ms = 0): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function names(): string[] {
    return [...document.querySelectorAll('.catalog-card__title')].map((node) => (node.textContent ?? '').trim());
}

function button(text: string): HTMLButtonElement {
    const found = [...document.querySelectorAll('button')].find((node) => (node.textContent ?? '').trim().startsWith(text));
    if (!found) throw new Error(`no button "${text}"`);
    return found as HTMLButtonElement;
}

beforeEach(async () => {
    const container = document.createElement('div');
    container.id = THEMES_SCREEN_CONTAINER;
    document.body.appendChild(container);
    document.documentElement.dataset.theme = 'matrix';
    (globalThis as { Themes?: unknown }).Themes = { applyTheme };
    themeFavorites.ids = [];
    applyTheme.mockClear();
    openCatalogScreen.mockClear();
    openThemesScreen();
    await settle();
});

afterEach(() => {
    unmountThemesScreen();
    document.body.innerHTML = '';
    delete (globalThis as { Themes?: unknown }).Themes;
});

describe('the themes page', () => {
    test('it opens into its container, re-reads the list, and routes #themes', () => {
        expect(document.querySelector('.themes-screen')).not.toBeNull();
        expect(refresh).toHaveBeenCalledWith(true);
        expect(isThemesHash('#themes')).toBe(true);
        expect(isThemesHash('#catalog')).toBe(false);
    });

    test('every installed theme is a card, bundled first', () => {
        expect(names()).toEqual(['Matrix', 'Rogue']);
    });

    test('every installed theme is the one warez card: 16:9 picture, name, three line brief, no meta or source line', () => {
        const cards = [...document.querySelectorAll<HTMLElement>('[data-theme-card] .catalog-card')];
        expect(cards).toHaveLength(2);
        for (const card of cards) {
            expect(card.getAttribute('data-kind')).toBe('theme');
            expect(card.querySelector('.catalog-card__media .tpv')).not.toBeNull();
            expect(card.querySelector('.catalog-card__brief')).not.toBeNull();
            expect(card.querySelector('.catalog-card__meta, [data-catalog-credit], .tcard-tags')).toBeNull();
        }
        expect(document.querySelector('.themes-grid')?.classList.contains('warez-grid')).toBe(true);
    });

    test('each preview paints its own manifest and never a page variable', () => {
        const previews = [...document.querySelectorAll<HTMLElement>('[data-theme-card] .tpv')];
        expect(previews).toHaveLength(2);
        const styles = previews.map((node) => node.getAttribute('style') ?? '');
        expect(styles[0]).toMatch(/--p-page:\s*#000800/);
        expect(styles[1]).toMatch(/--p-page:\s*#111111/);
        for (const style of styles) expect(style).not.toContain('var(');
    });

    test('an unsafe manifest value reaches no style attribute anywhere', () => {
        const every = [...document.querySelectorAll('[style]')].map((node) => node.getAttribute('style') ?? '').join(' ');
        expect(every).not.toMatch(/javascript|url\(/);
    });

    test('the live page theme is preselected, and selecting another does not apply it', async () => {
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('matrix');
        (document.querySelector('[data-theme-card="rogue"] .catalog-card__open') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('rogue');
        expect(applyTheme).not.toHaveBeenCalled();
    });

    test('the current global theme in the bar is a link that opens that theme in the inspector', async () => {
        (document.querySelector('[data-theme-card="rogue"] .catalog-card__open') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('rogue');
        const link = document.querySelector('.oc-page__bar button.themes-now') as HTMLButtonElement;
        expect(link.textContent?.trim()).toBe('Matrix');
        link.click();
        await settle();
        expect(document.querySelector('[data-inspector]')?.getAttribute('data-inspector')).toBe('matrix');
        expect(applyTheme).not.toHaveBeenCalled();
    });

    test('apply goes through the registry with persist, like the home cell', async () => {
        (document.querySelector('[data-theme-card="rogue"] .catalog-card__open') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('[data-theme-apply]') as HTMLButtonElement).click();
        expect(applyTheme).toHaveBeenCalledWith('rogue', { persist: true });
    });

    test('a star moves a theme into the favorites filter', async () => {
        (document.querySelector('[data-theme-card="rogue"] [data-act="card-star"]') as HTMLButtonElement).click();
        await settle();
        expect(themeFavorites.ids).toEqual(['rogue']);
        (document.querySelector('.oc-chip[aria-pressed="false"]:nth-child(2)') as HTMLButtonElement).click();
        await settle();
        expect(names()).toEqual(['Rogue']);
    });

    test('the search narrows the grid', async () => {
        const box = document.querySelector('.oc-page__bar input.oc-field') as HTMLInputElement;
        box.value = 'green';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(names()).toEqual(['Matrix']);
    });

    test('the library button opens the catalog on themes', () => {
        button('get more on warez').click();
        expect(openCatalogScreen).toHaveBeenCalledWith({ kind: 'theme' });
    });

    test('the guide carries a live submit button', async () => {
        button('build your own').click();
        await settle();
        const submit = button('submit a theme');
        expect(submit.disabled).toBe(false);
        expect(document.querySelector('.tbyo-code')?.textContent).toContain('"id": "night-ops"');
    });

    test('escape leaves it up and the host closes it', async () => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        await settle();
        expect(document.querySelector('.themes-screen')).not.toBeNull();
        openThemesScreen();
        await settle();
        expect(closeThemesScreen()).toBe(true);
        await settle();
        expect(document.querySelector('.themes-screen')).toBeNull();
    });
});

describe('the themes page on the shared frame', () => {
    beforeEach(async () => {
        unmountThemesScreen();
        openThemesScreen();
        await settle();
    });

    test('it wears the page frame and the shared primitives, not a frame of its own', () => {
        expect(document.querySelector('.oc-page.themes-screen')).not.toBeNull();
        expect(document.querySelector('.oc-titlebar .oc-titlebar__title')?.textContent).toBe('themes');
        expect(document.querySelector('.oc-page__bar input.oc-field[type="search"]')).not.toBeNull();
        expect(document.querySelectorAll('.oc-page__chips .oc-chip')).toHaveLength(5);
        expect(document.querySelector('[class*="tp-"]')).toBeNull();
    });

    test('library and guide are shared buttons in the bar, the strip has no close button', async () => {
        expect(document.querySelectorAll('.oc-page__tools button.oc-btn')).toHaveLength(2);
        expect(document.querySelector('[data-page-close]')).toBeNull();
        button('get more on warez').click();
        expect(openCatalogScreen).toHaveBeenCalledWith({ kind: 'theme' });
        button('build your own').click();
        await settle();
        expect(document.querySelector('.tbyo-code')).not.toBeNull();
    });

    test('the back button of a narrow pane lowers the inspector', async () => {
        (document.querySelector('[data-theme-card="rogue"] .catalog-card__open') as HTMLButtonElement).click();
        await settle();
        const body = document.querySelector('.themes-body') as HTMLElement;
        expect(body.classList.contains('themes-body--detail')).toBe(true);
        (document.querySelector('.themes-back') as HTMLButtonElement).click();
        await settle();
        expect(body.classList.contains('themes-body--detail')).toBe(false);
    });
});
