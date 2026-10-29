import { describe, expect, it } from 'vitest';
import { paletteOf, palettesFrom, pendingOf } from './theme-palettes';

const entry = {
    digest: 'a'.repeat(64),
    version: '1.0.0',
    cssVars: { '--color-bg': '#112233', '--color-accent': 'url(http://x)', '--color-fg': '#abcdef' },
    xterm: { background: '#000000' },
    ascii: false,
};

describe('theme palettes', () => {
    it('drops an unsafe value to the fallback and forces no artwork', () => {
        const p = paletteOf('n/snes', entry);
        expect(p.page).toBe('#112233');
        expect(p.accent).not.toContain('url');
        expect(p.artwork).toBeNull();
        expect(p.background).toBeNull();
    });

    it('maps every entry by id and reads pending', () => {
        const res = { items: { 'n/snes': entry }, pending: ['n/b'] };
        expect(palettesFrom(res).has('n/snes')).toBe(true);
        expect(pendingOf(res)).toEqual(['n/b']);
    });

    it('answers empty for no response', () => {
        expect(palettesFrom(null).size).toBe(0);
        expect(pendingOf(undefined)).toEqual([]);
    });
});
