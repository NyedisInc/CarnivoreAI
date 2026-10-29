/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Arrangement from '../drawer/arrangement';
import * as Store from '../drawer/store';
import { onRowKeydown, onPinClick } from './row-reorder';

const activate = vi.hoisted(() => vi.fn());
vi.mock('./row-activate', () => ({ activateRow: activate, armAsleepRow: () => false }));

const win = window as unknown as Record<string, any>;
let list: HTMLElement;
let live: HTMLElement;
let drawn: Array<{ name: string; band: string }>;

function stored(): Record<string, any> {
    return JSON.parse(localStorage.getItem(Store.STORAGE_KEY) || '{}');
}

function shown(): string[] {
    return Array.from(list.querySelectorAll<HTMLElement>('.session-sidebar-row')).map((e) => `${e.dataset.band}:${e.dataset.name}`);
}

function paint(): void {
    for (const c of Array.from(list.children)) {
        if (document.activeElement === c) (document.activeElement as HTMLElement).blur();
        list.removeChild(c);
    }
    for (const r of drawn) {
        const el = document.createElement('div');
        el.className = 'session-sidebar-row';
        el.dataset.name = r.name;
        el.dataset.band = r.band;
        el.tabIndex = -1;
        list.appendChild(el);
    }
}

function repaintFlat(): void {
    const names = drawn.map((r) => r.name);
    const known = new Set(Store.current().order);
    const ordered = Store.current().order.filter((n) => names.includes(n)).concat(names.filter((n) => !known.has(n)));
    const sorted = ordered.filter((n) => Store.isPinned(n)).concat(ordered.filter((n) => !Store.isPinned(n)));
    drawn = sorted.map((name) => ({ name, band: 'flat' }));
    paint();
}

function mount(pinned: string[], order: string[], repaint: () => void): void {
    localStorage.setItem(Store.STORAGE_KEY, JSON.stringify({ v: 1, pinned, order }));
    Store.load();
    win.SessionSidebar = { listEl: list, repaint, activateRow: activate };
    repaint();
}

function key(row: Element, k: string, init: KeyboardEventInit = {}): void {
    (row as HTMLElement).focus();
    const e = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init });
    Object.defineProperty(e, 'target', { value: row });
    onRowKeydown(e, row as HTMLElement);
}

function rowOf(name: string, band?: string): HTMLElement {
    const band_ = band === undefined ? '' : `[data-band="${band}"]`;
    return list.querySelector<HTMLElement>(`.session-sidebar-row[data-name="${name}"]${band_}`)!;
}

beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="session-sidebar-list"></div><div id="session-sidebar-live"></div>';
    list = document.getElementById('session-sidebar-list')!;
    live = document.getElementById('session-sidebar-live')!;
    drawn = ['a', 'b', 'c'].map((name) => ({ name, band: 'flat' }));
    activate.mockClear();
});

afterEach(() => { delete win.SessionSidebar; });

describe('ITEM 46: the flat list, by dispatched keys', () => {
    it('Alt+ArrowUp MOVES the row, persists it, and focus survives the repaint', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('b'), 'ArrowUp', { altKey: true });
        expect(shown()).toEqual(['flat:b', 'flat:a', 'flat:c']);
        expect(stored().order).toEqual(['b', 'a', 'c']);
        expect((document.activeElement as HTMLElement).dataset.name).toBe('b');
    });

    it('a BARE ArrowUp moves focus and leaves the order alone', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('b'), 'ArrowUp');
        expect(shown()).toEqual(['flat:a', 'flat:b', 'flat:c']);
        expect((document.activeElement as HTMLElement).dataset.name).toBe('a');
        expect(localStorage.getItem(Store.STORAGE_KEY)).toContain('"order":["a","b","c"]');
    });

    it('the list is ONE tab stop', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('b'), 'ArrowUp');
        const stops = Array.from(list.children).filter((e) => e.getAttribute('tabindex') === '0');
        expect(stops).toHaveLength(1);
        expect((stops[0] as HTMLElement).dataset.name).toBe('a');
    });

    it('"p" pins the focused row from the keyboard alone, and it moves to the top at once', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('c'), 'p');
        expect(stored().pinned).toEqual(['c']);
        expect((list.children[0] as HTMLElement).dataset.name).toBe('c');
    });

    it('Home and End reach the ends without a mouse', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('b'), 'End');
        expect((document.activeElement as HTMLElement).dataset.name).toBe('c');
        key(document.activeElement!, 'Home');
        expect((document.activeElement as HTMLElement).dataset.name).toBe('a');
    });

    it('a refused move at the list edge is ANNOUNCED', () => {
        mount(['a'], ['a', 'b', 'c'], repaintFlat);
        key(rowOf('a'), 'ArrowUp', { altKey: true });
        expect(live.textContent).toMatch(/already at the top/);
    });

    it('Enter activates the row; a key on a nested control does not', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        const a = rowOf('a');
        const inner = document.createElement('button');
        a.appendChild(inner);
        key(inner, 'Enter');
        expect(activate).not.toHaveBeenCalled();
        key(a, 'Enter');
        expect(activate).toHaveBeenCalledTimes(1);
    });

    it('the pin button toggles the pin and stops the click', () => {
        mount([], ['a', 'b', 'c'], repaintFlat);
        const btn = document.createElement('button');
        btn.setAttribute('data-pin-session', 'b');
        rowOf('b').appendChild(btn);
        const e = new MouseEvent('click', { bubbles: true, cancelable: true });
        onPinClick(e, btn);
        expect(stored().pinned).toEqual(['b']);
        expect(e.defaultPrevented).toBe(true);
    });
});

describe('KEYBOARD: a band keeps its own order', () => {
    function repaintBands(): void {
        const all = ['a', 'b', 'c'];
        const p1 = Arrangement.orderBand('p:1', all.map((name) => ({ name })));
        drawn = [{ name: 'a', band: 'pinned' }, ...p1.map((r) => ({ name: r.name, band: 'p:1' }))];
        paint();
    }

    it('Alt+ArrowDown moves a row inside its project band only; focus stays on that copy', () => {
        mount(['a'], ['a', 'b', 'c'], repaintBands);
        key(rowOf('a', 'p:1'), 'ArrowDown', { altKey: true });
        expect(shown()).toEqual(['pinned:a', 'p:1:b', 'p:1:a', 'p:1:c']);
        expect(stored().bands['p:1']).toEqual(['b', 'a', 'c']);
        expect(stored().order).toEqual(['a', 'b', 'c']);
        expect(stored().pinned).toEqual(['a']);
        const f = document.activeElement as HTMLElement;
        expect(`${f.dataset.band}:${f.dataset.name}`).toBe('p:1:a');
        expect(live.textContent).toMatch(/position 2 of 3/);
    });

    it('the band edge is refused and announced', () => {
        mount(['a'], ['a', 'b', 'c'], repaintBands);
        key(rowOf('c', 'p:1'), 'ArrowDown', { altKey: true });
        expect(shown()).toEqual(['pinned:a', 'p:1:a', 'p:1:b', 'p:1:c']);
        expect(live.textContent).toMatch(/already at the bottom/);
    });
});
