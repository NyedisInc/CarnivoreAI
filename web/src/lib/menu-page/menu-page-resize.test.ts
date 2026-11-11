/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { clampWidth, drawerResize, readDrawerWidth, writeDrawerWidth } from './menu-page-resize';

function store(): Storage {
    const m = new Map<string, string>();
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) } as Storage;
}

describe('menu page drawer resize', () => {
    it('clamps between the floor and the available space, floor winning when space is short', () => {
        expect(clampWidth(100, 672, 1120)).toBe(672);
        expect(clampWidth(900, 672, 1120)).toBe(900);
        expect(clampWidth(5000, 672, 1120)).toBe(1120);
        expect(clampWidth(900, 672, 500)).toBe(672);
    });
    it('persists per page, ignores junk and resets on null', () => {
        const s = store();
        expect(readDrawerWidth('a', s)).toBeNull();
        writeDrawerWidth('a', 812.4, s);
        expect(readDrawerWidth('a', s)).toBe(812);
        expect(readDrawerWidth('b', s)).toBeNull();
        s.setItem('carnivore.menu-page.width.b', 'x');
        expect(readDrawerWidth('b', s)).toBeNull();
        writeDrawerWidth('a', null, s);
        expect(readDrawerWidth('a', s)).toBeNull();
    });
});

describe('menu page drawer cap (#2923)', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/lib/menu-page/menu-page.css'), 'utf8');
    const px = (name: string): number => Number(new RegExp(`${name}:\\s*(\\d+)px`).exec(css)?.[1]);
    it('caps at the menu rail + three theme columns + the detail panel, and the grow width stays under it', () => {
        expect(px('--oc-drawer-max-w')).toBe(1580);
        expect(px('--oc-drawer-max-w')).toBeGreaterThanOrEqual(300 + 32 + 860 + 380);
        expect(px('--oc-drawer-max-w')).toBeLessThan(1789);
        expect(px('--oc-drawer-grow-w')).toBeLessThanOrEqual(px('--oc-drawer-max-w'));
        expect(css).toContain('--oc-drawer-shadow: 1px 0 0 var(--oc-line-rule), 14px 0 16px -12px var(--oc-shadow-lift)');
    });
    it('the drag handle clamps at the page max-width, not just the window', () => {
        const host = document.createElement('div');
        host.id = 'warez-screen';
        const page = document.createElement('div');
        page.style.minWidth = '300px';
        page.style.maxWidth = '900px';
        const handle = document.createElement('div');
        host.append(page);
        page.append(handle);
        document.body.append(host);
        const off = drawerResize(() => page)(handle);
        const at = (type: string, clientX: number): void => void handle.dispatchEvent(new MouseEvent(type, { clientX, button: 0 }));
        at('pointerdown', 0);
        at('pointermove', 5000);
        expect(page.style.getPropertyValue('--oc-drawer-w')).toBe('900px');
        at('pointerup', 5000);
        off();
        host.remove();
        window.localStorage.removeItem('carnivore.menu-page.width.warez-screen');
    });
});

describe('menu page grid limit (#2923)', () => {
    it('a warez grid never has more than three columns and a page opens at the cap when there is room', () => {
        const grid = readFileSync(resolve(process.cwd(), 'src/lib/catalog/warez-card.css'), 'utf8');
        expect(grid).toContain('minmax(max(276px, calc((100% - 32px) / 3)), 1fr)');
        const css = readFileSync(resolve(process.cwd(), 'src/lib/menu-page/menu-page.css'), 'utf8');
        expect(css).toContain('--oc-drawer-grow-w: 1580px');
    });
});
