/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import { initMenuPageShell, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';
import { MENU_PAGE_SURFACE_CLASS, SURFACE_INSET_VARS, createSurfaceTracker, findSurface, insetsOf } from './menu-page-surface';

type Box = { x: number; y: number; width: number; height: number };

let box: Box;
let surface: HTMLElement;
let screen: HTMLElement;
let terminal: HTMLElement;
let observers: Array<{ cb: () => void; seen: Element[]; live: boolean }>;
let stop: () => void = () => {};

function lay(el: HTMLElement, get: () => Box): void {
    el.getBoundingClientRect = () => {
        const b = get();
        return { ...b, left: b.x, top: b.y, right: b.x + b.width, bottom: b.y + b.height, toJSON: () => b } as DOMRect;
    };
}

function insets(): string[] {
    return SURFACE_INSET_VARS.map((name) => document.documentElement.style.getPropertyValue(name));
}

beforeEach(() => {
    resetMenuPageShell();
    document.body.className = '';
    document.documentElement.removeAttribute('style');
    Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true, writable: true });
    Object.defineProperty(window, 'innerHeight', { value: 900, configurable: true, writable: true });
    observers = [];
    (window as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
        entry: { cb: () => void; seen: Element[]; live: boolean };
        constructor(cb: () => void) {
            this.entry = { cb, seen: [], live: true };
            observers.push(this.entry);
        }
        observe(el: Element): void {
            this.entry.seen.push(el);
        }
        disconnect(): void {
            this.entry.live = false;
        }
    };
    box = { x: 320, y: 0, width: 1110, height: 890 };
    screen = document.createElement('div');
    screen.id = 'terminal-screen';
    screen.className = 'screen active';
    const grid = document.createElement('div');
    grid.id = 'terminal-grid';
    surface = document.createElement('div');
    surface.className = 'oc-surface oc-surface-zoomable';
    terminal = document.createElement('div');
    terminal.id = 'terminal';
    surface.append(terminal);
    grid.append(surface);
    // the bottom bar
    for (const edge of ['side', 'bottom']) {
        const rail = document.createElement('nav');
        rail.setAttribute('data-session-rail', '');
        rail.setAttribute('data-rail-edge', edge);
        grid.append(rail);
    }
    const bar = document.createElement('div');
    bar.className = 'info';
    screen.append(grid, bar);
    document.body.append(screen);
    lay(surface, () => box);
});

afterEach(() => {
    stop();
    stop = () => {};
    document.body.replaceChildren();
    document.body.className = '';
    delete document.body.dataset.menuPage;
});

test('the surface is the .oc-surface in the terminal grid, and the page is pointed at its rect', () => {
    expect(findSurface(document, window)).toBe(surface);
    expect(insetsOf(surface, window)).toEqual({ top: 0, left: 320, right: 10, bottom: 10 });
    const tracker = createSurfaceTracker({ doc: document, win: window });
    expect(tracker.start()).toBe(true);
    expect(insets()).toEqual(['0px', '320px', '10px', '10px']);
    expect(document.body.classList.contains(MENU_PAGE_SURFACE_CLASS)).toBe(true);
    tracker.stop();
});

test('the Home screen\'s surface is the one measured when no session grid is up', () => {
    document.getElementById('terminal-grid')!.remove();
    const home = document.createElement('div');
    home.id = 'launchpad-screen';
    home.className = 'screen active';
    const homeSurface = document.createElement('div');
    homeSurface.className = 'oc-surface';
    lay(homeSurface, () => ({ x: 320, y: 62, width: 1100, height: 800 }));
    home.append(homeSurface);
    document.body.append(home);
    expect(findSurface(document, window)).toBe(homeSurface);
});

test('what is under the page stays mounted, shown and the same size: it is only made inert', () => {
    const tracker = createSurfaceTracker({ doc: document, win: window });
    tracker.start();
    expect(terminal.isConnected).toBe(true);
    expect(surface.hasAttribute('inert')).toBe(true);
    expect(screen.hidden).toBe(false);
    expect(screen.style.display).toBe('');
    expect(screen.style.visibility).toBe('');
    expect(surface.getAttribute('style')).toBeNull();
    expect(box).toEqual({ x: 320, y: 0, width: 1110, height: 890 });
    tracker.stop();
    expect(surface.hasAttribute('inert')).toBe(false);
    expect(terminal.isConnected).toBe(true);
});

test('only the surface is inert: the widget drawers, their rails and the bottom bar stay live and scrollable (#1774)', () => {
    const tracker = createSurfaceTracker({ doc: document, win: window });
    tracker.start();
    expect(surface.hasAttribute('inert')).toBe(true);
    expect(screen.hasAttribute('inert')).toBe(false);
    const live = document.querySelectorAll('[data-session-rail], .info');
    expect(live.length).toBe(3);
    for (const el of live) expect(el.closest('[inert]'), el.outerHTML).toBeNull();
    const next = document.createElement('div');
    next.className = 'oc-surface';
    lay(next, () => box);
    surface.replaceWith(next);
    tracker.refresh();
    expect(next.hasAttribute('inert')).toBe(true);
    expect(surface.hasAttribute('inert')).toBe(false);
    tracker.stop();
    expect(next.hasAttribute('inert')).toBe(false);
});

test('the page follows the surface when a drawer opens or the window resizes', () => {
    const tracker = createSurfaceTracker({ doc: document, win: window });
    tracker.start();
    box = { x: 320, y: 0, width: 790, height: 890 };
    const live = observers.filter((o) => o.live);
    expect(live.length).toBe(1);
    expect(live[0]!.seen).toContain(surface);
    live[0]!.cb();
    expect(insets()).toEqual(['0px', '320px', '330px', '10px']);
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true, writable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true, writable: true });
    box = { x: 320, y: 0, width: 870, height: 790 };
    window.dispatchEvent(new Event('resize'));
    expect(insets()).toEqual(['0px', '320px', '10px', '10px']);
    tracker.stop();
    expect(observers.every((o) => !o.live)).toBe(true);
});

test('stopping puts the viewport-wide cover back, and an idle app measures nothing', () => {
    const tracker = createSurfaceTracker({ doc: document, win: window });
    tracker.start();
    tracker.stop();
    expect(insets()).toEqual(['', '', '', '']);
    expect(document.body.classList.contains(MENU_PAGE_SURFACE_CLASS)).toBe(false);
    box = { x: 0, y: 0, width: 5, height: 5 };
    window.dispatchEvent(new Event('resize'));
    expect(insets()).toEqual(['', '', '', '']);
});

test('below 1024 there is no surface mode: the phone keeps its full-screen page', () => {
    Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true, writable: true });
    expect(findSurface(document, window)).toBeNull();
    const tracker = createSurfaceTracker({ doc: document, win: window });
    expect(tracker.start()).toBe(false);
    expect(document.body.classList.contains(MENU_PAGE_SURFACE_CLASS)).toBe(false);
    expect(surface.hasAttribute('inert')).toBe(false);
    tracker.stop();
});

test('with no surface on the page (nothing mounted yet) the page keeps the viewport-wide cover', () => {
    surface.remove();
    expect(createSurfaceTracker({ doc: document, win: window }).start()).toBe(false);
});

test('the shell puts a page over the surface when it opens and takes it off when it closes, content untouched', async () => {
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        ns[page.closer] = vi.fn(() => document.getElementById(page.containerId)!.replaceChildren());
        const div = document.createElement('div');
        div.id = page.containerId;
        document.body.append(div);
    }
    const deps: ShellDeps = { selectTab: vi.fn(), web: () => ns };
    stop = initMenuPageShell(document, deps);
    const root = document.createElement('div');
    document.getElementById('settings-screen')!.append(root);
    await Promise.resolve();
    await Promise.resolve();
    expect(document.body.classList.contains('menu-page-open')).toBe(true);
    expect(document.body.classList.contains(MENU_PAGE_SURFACE_CLASS)).toBe(true);
    expect(insets()).toEqual(['0px', '320px', '10px', '10px']);
    expect(terminal.isConnected).toBe(true);
    root.remove();
    await Promise.resolve();
    await Promise.resolve();
    expect(document.body.classList.contains('menu-page-open')).toBe(false);
    expect(document.body.classList.contains(MENU_PAGE_SURFACE_CLASS)).toBe(false);
    expect(insets()).toEqual(['', '', '', '']);
    expect(surface.hasAttribute('inert')).toBe(false);
    expect(terminal.isConnected).toBe(true);
});

test('an open Layout command bar above the grid is covered: the page reaches the top of it', () => {
    const bar = document.createElement('div');
    bar.id = 'layout-command-bar';
    screen.prepend(bar);
    lay(bar, () => ({ x: 320, y: 0, width: 1100, height: 40 }));
    lay(surface, () => ({ x: 320, y: 40, width: 1100, height: 850 }));
    const tracker = createSurfaceTracker({ doc: document, win: window });
    tracker.start();
    expect(insets()[0]).toBe('0px');
    lay(bar, () => ({ x: 320, y: 0, width: 1100, height: 0 }));
    tracker.refresh();
    expect(insets()[0]).toBe('40px');
    tracker.stop();
});

test('the stylesheet points the page at the surface and stops hiding what is under it', () => {
    const css = readFileSync(resolve(__dirname, 'menu-page.css'), 'utf8');
    const rule = css.match(/body\.menu-page-surface \.oc-page:not\(\.oc-page--embedded\)\s*\{([^}]*)\}/);
    expect(rule, 'the surface rule exists').not.toBeNull();
    for (const [prop, name] of [['top', 'top'], ['left', 'left'], ['right', 'right'], ['bottom', 'bottom']]) {
        expect(rule![1]).toContain(`${prop}: var(--menu-surface-${name})`);
    }
    expect(rule![1]).toContain('padding-left: 0');
    const hide = css.match(/([^{}]*)\{\s*visibility: hidden;\s*\}/);
    expect(hide![1]).toContain(':not(.menu-page-surface)');
    expect(hide![1]).not.toMatch(/body\.menu-page-open >/);
});

test('every menu page root is the shared Page frame: the Elite and Automations screens draw through Page, not their own root and title row (wrapper package T-1)', () => {
    const screens = ['elite/EliteScreen.svelte', 'automations/AutomationsScreen.svelte'];
    for (const file of screens) {
        const src = readFileSync(resolve(__dirname, '..', file), 'utf8');
        expect(src, `${file} imports Page`).toMatch(/import Page from '[./]*opscenter\/ui\/Page\.svelte'/);
        expect(src, `${file} opens a <Page>`).toMatch(/<Page\b/);
        expect(src, `${file} draws no .oc-page root of its own`).not.toMatch(/<div[^>]*class="oc-page/);
        expect(src, `${file} draws no .pl-titlebar of its own`).not.toMatch(/<div[^>]*class="pl-titlebar/);
    }
});
