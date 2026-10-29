import { describe, expect, test } from 'vitest';
import { filterCounts, matchesQuery, visibleThemes } from './themes-page-model';
import { previewPalette, previewStyle, NEUTRAL } from './preview-palette';
import type { ThemeManifest } from '../../opscenter/api';

function theme(id: string, over: Partial<ThemeManifest> = {}): ThemeManifest {
    return { id, name: id, description: '', author: null, version: null, cssVars: {}, xterm: {}, source: 'builtin', ...over };
}

const ZETA = theme('zeta', { source: 'user', description: 'deep red glow' });
const LIST = [
    ZETA,
    theme('matrix', { cssVars: { '--ascii-display': 'block' } }),
    theme('alpha', { author: 'acme' }),
];

describe('the model', () => {
    test('bundled first, then by name', () => {
        expect(visibleThemes(LIST, 'all', '', []).map((m) => m.id)).toEqual(['alpha', 'matrix', 'zeta']);
    });

    test('each filter keeps its own set', () => {
        expect(visibleThemes(LIST, 'favorites', '', ['zeta']).map((m) => m.id)).toEqual(['zeta']);
        expect(visibleThemes(LIST, 'user', '', []).map((m) => m.id)).toEqual(['zeta']);
        expect(visibleThemes(LIST, 'builtin', '', []).map((m) => m.id)).toEqual(['alpha', 'matrix']);
        expect(visibleThemes(LIST, 'ascii', '', []).map((m) => m.id)).toEqual(['matrix']);
    });

    test('every search word must match somewhere', () => {
        expect(matchesQuery(ZETA, 'red deep')).toBe(true);
        expect(matchesQuery(ZETA, 'red blue')).toBe(false);
        expect(visibleThemes(LIST, 'all', 'acme', []).map((m) => m.id)).toEqual(['alpha']);
    });

    test('a star on a removed theme is not counted', () => {
        expect(filterCounts(LIST, ['zeta', 'gone']).favorites).toBe(1);
        expect(filterCounts(null, []).all).toBe(0);
    });
});

describe('a preview wears only its own manifest', () => {
    const own = theme('neon', {
        cssVars: { '--color-bg-page': '#010203', '--color-accent': 'rgb(1, 2, 3)', '--color-danger': 'url(javascript:x)' },
        xterm: { background: '#0a0b0c', red: '#ff0000', green: 'expression(alert(1))' },
    });

    test('its colours come from the manifest', () => {
        const p = previewPalette(own);
        expect(p.page).toBe('#010203');
        expect(p.accent).toBe('rgb(1, 2, 3)');
        expect(p.termBg).toBe('#0a0b0c');
    });

    test('an unsafe value never reaches the style, and falls back inside the manifest', () => {
        const p = previewPalette(own);
        expect(p.danger).toBe('#ff0000');
        expect(p.ansi[2]).not.toContain('expression');
        const style = previewStyle(p);
        expect(style).not.toMatch(/url\(|expression|javascript/);
    });

    test('no page variable is ever a fallback', () => {
        const style = previewStyle(previewPalette(theme('empty')));
        expect(style).not.toContain('var(');
        expect(style).toContain(`--p-page:${NEUTRAL.ground}`);
    });

    test('artwork resolves under the theme source folder, and a bad image name is dropped', () => {
        expect(previewPalette(theme('a', { background: { image: 'background.webp' } })).background).toBe('/static/css/themes/a/background.webp');
        expect(previewPalette(theme('a', { background: { image: '../x.svg' } })).background).toBeNull();
        expect(previewPalette(theme('a', { source: 'builtin' })).artwork).toBe('/static/css/themes/a/preview.webp');
        expect(previewPalette(theme('a', { source: 'user' })).artwork).toBe('/themes/a/preview.webp');
        expect(previewPalette(theme('a', { source: 'user', background: { image: 'background.webp' } })).background).toBe('/themes/a/background.webp');
        expect(previewPalette(theme('a', { source: 'user', background: { image: '../x.svg' } })).background).toBeNull();
    });
});
