/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { clampWidth, drawerResize } from './menu-page-resize';
import { readDrawerWidth, WIDTH_FIELD, WIDTH_STORAGE_KEY, writeDrawerWidth } from './menu-page-width';

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
});

function mountPage(id: string, min: number, max: number): { page: HTMLElement; handle: HTMLElement; off: () => void; gone: () => void } {
    const host = document.createElement('div');
    host.id = id;
    const page = document.createElement('div');
    page.style.minWidth = `${min}px`;
    page.style.maxWidth = `${max}px`;
    const handle = document.createElement('div');
    host.append(page);
    page.append(handle);
    document.body.append(host);
    const off = drawerResize(() => page)(handle);
    return { page, handle, off, gone: () => host.remove() };
}
const fire = (el: HTMLElement, type: string, clientX = 0): void => void el.dispatchEvent(new MouseEvent(type, { clientX, button: 0 }));
const widthOf = (page: HTMLElement): string => page.style.getPropertyValue('--oc-drawer-w');

describe('ONE shared width for every menu page (Joe (ccsliinc), 2026-11-11)', () => {
    afterEach(() => {
        window.localStorage.clear();
        document.body.innerHTML = '';
    });
    it('stores one width for every page: junk reads as nothing, null forgets', () => {
        const s = store();
        expect(readDrawerWidth(s)).toBeNull();
        writeDrawerWidth(812.4, s);
        expect(readDrawerWidth(s)).toBe(812);
        s.setItem(WIDTH_STORAGE_KEY, 'x');
        expect(readDrawerWidth(s)).toBeNull();
        writeDrawerWidth(null, s);
        expect(readDrawerWidth(s)).toBeNull();
    });
    it('a width dragged on one page is what a different page opens at, and it survives closing and reloading', () => {
        const a = mountPage('warez-screen', 300, 900);
        fire(a.handle, 'pointerdown');
        fire(a.handle, 'pointermove', 700);
        fire(a.handle, 'pointerup', 700);
        expect(widthOf(a.page)).toBe('700px');
        a.off();
        a.gone(); // closed
        const b = mountPage('settings-screen', 300, 2000);
        expect(widthOf(b.page)).toBe('700px');
        expect(b.handle.getAttribute('aria-valuenow')).toBe('700');
        b.off();
    });
    it('a page whose floor is wider opens at its floor and a narrower ceiling holds, without forgetting the shared width', () => {
        writeDrawerWidth(700);
        const wide = mountPage('stacked', 800, 2000);
        expect(widthOf(wide.page)).toBe('800px');
        const narrow = mountPage('narrow', 300, 600);
        expect(widthOf(narrow.page)).toBe('600px');
        expect(readDrawerWidth()).toBe(700);
    });
    it('the arrow keys set the shared width too', () => {
        const a = mountPage('one', 300, 900);
        a.page.getBoundingClientRect = (): DOMRect => ({ width: 500, left: 0 }) as DOMRect; // jsdom has no layout
        a.handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
        a.handle.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowRight', bubbles: true }));
        const b = mountPage('two', 300, 900);
        expect(widthOf(a.page)).toBe('516px');
        expect(widthOf(b.page)).toBe('516px');
    });
    it('a double-click forgets the shared width for every page', () => {
        writeDrawerWidth(700);
        const a = mountPage('one', 300, 900);
        fire(a.handle, 'dblclick');
        expect(widthOf(a.page)).toBe('');
        expect(readDrawerWidth()).toBeNull();
        expect(widthOf(mountPage('two', 300, 900).page)).toBe('');
    });
    it('never reads the old per-page keys', () => {
        window.localStorage.setItem('carnivore.menu-page.width.warez-screen', '640');
        expect(widthOf(mountPage('warez-screen', 300, 900).page)).toBe('');
    });
    it('goes through the shared preference when the bridge is loaded, and shows the shared value first', async () => {
        const written: Array<[string, unknown]> = [];
        (globalThis as Record<string, unknown>).PreferenceBridge = {
            read: () => 640,
            write: async (f: string, v: unknown, local: () => void) => (local(), written.push([f, v])),
        };
        try {
            const a = mountPage('one', 300, 900);
            expect(widthOf(a.page)).toBe('640px');
            fire(a.handle, 'pointerdown');
            fire(a.handle, 'pointermove', 520);
            fire(a.handle, 'pointerup', 520);
            expect(written).toEqual([[WIDTH_FIELD, 520]]);
            fire(a.handle, 'dblclick');
            expect(written[1]).toEqual([WIDTH_FIELD, null]);
        } finally {
            delete (globalThis as Record<string, unknown>).PreferenceBridge;
        }
    });
});

type Written = Array<[string, unknown]>;
function fakeBridge(status = 'committed', preferences?: Record<string, unknown>): { written: Written; remote: (v: unknown) => void } {
    const written: Written = [];
    let apply: (v: unknown) => void = () => {};
    (globalThis as Record<string, unknown>).PreferenceBridge = {
        read: (_f: string, fallback: () => unknown) => fallback(),
        write: async (f: string, v: unknown, local: () => void) => (local(), written.push([f, v]), { status }),
        follow: (_f: string, cb: (v: unknown) => void) => ((apply = cb), () => {}),
    };
    if (preferences) (globalThis as Record<string, unknown>).Preferences = preferences;
    return { written, remote: (v) => apply(v) };
}
function dropBridge(): void {
    delete (globalThis as Record<string, unknown>).PreferenceBridge;
    delete (globalThis as Record<string, unknown>).Preferences;
}

describe('the handle saves only a real drag (review of the earlier drag change)', () => {
    afterEach(() => {
        dropBridge();
        vi.useRealTimers();
        window.localStorage.clear();
        document.body.innerHTML = '';
    });
    it('a plain click saves nothing and a double-click only forgets (no stray save racing the reset)', () => {
        const { written } = fakeBridge();
        const a = mountPage('one', 300, 900);
        fire(a.handle, 'pointerdown', 500);
        fire(a.handle, 'pointerup', 500);
        expect(written).toEqual([]);
        fire(a.handle, 'pointerdown', 500);
        fire(a.handle, 'pointerup', 501);
        fire(a.handle, 'dblclick', 501);
        expect(written).toEqual([[WIDTH_FIELD, null]]);
    });
    it('pointercancel never saves and puts the page back', () => {
        const { written } = fakeBridge();
        const a = mountPage('one', 300, 900);
        fire(a.handle, 'pointerdown', 0);
        fire(a.handle, 'pointermove', 700);
        expect(widthOf(a.page)).toBe('700px');
        fire(a.handle, 'pointercancel', 0);
        expect(written).toEqual([]);
        expect(widthOf(a.page)).toBe('');
    });
    it('the arrow keys paint every press and save once, after a pause or when the key comes up', () => {
        vi.useFakeTimers();
        const { written } = fakeBridge();
        const a = mountPage('one', 300, 900);
        let w = 500;
        a.page.getBoundingClientRect = (): DOMRect => ({ width: w, left: 0 }) as DOMRect;
        const press = (): void => {
            a.handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            w = parseFloat(widthOf(a.page));
        };
        press();
        press();
        press();
        expect(widthOf(a.page)).toBe('548px');
        expect(written).toEqual([]);
        vi.advanceTimersByTime(400);
        expect(written).toEqual([[WIDTH_FIELD, 548]]);
        press();
        a.handle.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowRight', bubbles: true }));
        expect(written).toEqual([[WIDTH_FIELD, 548], [WIDTH_FIELD, 564]]);
    });
    it('a change made elsewhere (a reset on another browser) updates the cache and repaints every mounted page', () => {
        const { remote } = fakeBridge();
        const a = mountPage('one', 300, 900);
        remote(640);
        expect(widthOf(a.page)).toBe('640px');
        expect(window.localStorage.getItem(WIDTH_STORAGE_KEY)).toBe('640');
        remote(null);
        expect(widthOf(a.page)).toBe('');
        expect(window.localStorage.getItem(WIDTH_STORAGE_KEY)).toBeNull();
    });
    it('a stale save is retried once, and a failure is logged, never swallowed', async () => {
        const retry = vi.fn(async () => ({ status: 'failed', detail: 'nope' }));
        fakeBridge('stale_revision', { retry });
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const a = mountPage('one', 300, 900);
        fire(a.handle, 'pointerdown', 0);
        fire(a.handle, 'pointermove', 700);
        fire(a.handle, 'pointerup', 700);
        await new Promise((r) => setTimeout(r, 0));
        expect(retry).toHaveBeenCalledTimes(1);
        expect(retry).toHaveBeenCalledWith(WIDTH_FIELD);
        expect(warn).toHaveBeenCalled();
        warn.mockRestore();
    });
    it('the shared value is where the right edge sits: a page beside the settings list (offset) is narrower by the offset', () => {
        writeDrawerWidth(700);
        const host = document.createElement('div');
        const page = document.createElement('div');
        page.style.minWidth = '300px';
        page.style.maxWidth = '2000px';
        page.style.setProperty('--oc-drawer-offset', '240px');
        const handle = document.createElement('div');
        host.append(page);
        page.append(handle);
        document.body.append(host);
        drawerResize(() => page)(handle);
        expect(widthOf(page)).toBe('460px');
        fire(handle, 'pointerdown', 0);
        fire(handle, 'pointermove', 400);
        fire(handle, 'pointerup', 400);
        expect(readDrawerWidth()).toBe(640);
    });
});

describe('the resize handle wears the shared layer (thick, colored, brighter when used)', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/opscenter/page.css'), 'utf8');
    const block = (sel: string): string => new RegExp(`${sel.replace(/[.:\\[\\]=-]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
    it('a wide hit area, a 4px bar in an --oc token, brighter on hover, focus and drag, no hardcoded color', () => {
        const hit = block('.oc-page__resize');
        expect(Number(/width:\s*(\d+)px/.exec(hit)?.[1])).toBeGreaterThanOrEqual(12);
        const bar = block('.oc-page__resize::after');
        expect(Number(/width:\s*(\d+)px/.exec(bar)?.[1])).toBe(4);
        expect(bar).toContain('background: var(--oc-orange-dim)');
        const lit = /\.oc-page__resize:hover::after,[^{]*\{([^}]*)\}/.exec(css)?.[1] ?? '';
        expect(lit).toContain('var(--oc-orange-bright)');
        expect(css).toContain('.oc-page__resize[data-dragging]::after');
        expect(Number(/right:\s*(-\d+)px/.exec(hit)?.[1])).toBeLessThan(0);
        expect(css).toMatch(/body\.menu-page-surface \.oc-page:not\(\.oc-page--embedded\) \{[^}]*overflow: visible;/);
        expect(hit + bar + lit).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i);
    });
});

describe('menu page drawer cap (#2923)', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/opscenter/tokens.css'), 'utf8');
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
        window.localStorage.removeItem(WIDTH_STORAGE_KEY);
    });
});

describe('menu page grid limit (#2923)', () => {
    it('a warez grid never has more than three columns and a page opens at the cap when there is room', () => {
        const grid = readFileSync(resolve(process.cwd(), 'src/lib/catalog/warez-card.css'), 'utf8');
        expect(grid).toContain('minmax(max(276px, calc((100% - 32px) / 3)), 1fr)');
        const css = readFileSync(resolve(process.cwd(), 'src/opscenter/tokens.css'), 'utf8');
        expect(css).toContain('--oc-drawer-grow-w: 1580px');
    });
});
