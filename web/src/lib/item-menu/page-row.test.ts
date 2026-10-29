/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { LONG_PRESS_MS } from '../sidebar-shell/row-menu-gestures';
import { flushSync } from 'svelte';
import { closeItemMenu } from './open.svelte';
import { forwardMenuKey, pageRowMenu, type PageRowMenu } from './page-row';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

let row: HTMLElement;

beforeEach(() => {
    row = document.createElement('div');
    row.tabIndex = 0;
    document.body.append(row);
});

afterEach(() => {
    closeItemMenu();
    document.body.replaceChildren();
});

function menu(run: () => void, onOpen?: () => void): PageRowMenu {
    return {
        type: 'pagerow',
        ctx: { label: 'row menu', nodes: [{ id: 'edit', label: 'edit', run }, { id: 'delete', label: 'delete', danger: true, sep: true, run: () => {} }] },
        onOpen,
    };
}

function wire(source: () => PageRowMenu | null): void {
    const props = pageRowMenu(source);
    for (const [name, handler] of Object.entries(props)) row.addEventListener(name.slice(2).replace(/capture$/, ''), handler as EventListener, name.endsWith('capture'));
}

function rightClick(): MouseEvent {
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 12, clientY: 12 });
    row.dispatchEvent(event);
    flushSync();
    return event;
}

test('a right click opens the declared actions in the one item menu, claims the click and runs onOpen first', () => {
    const run = vi.fn();
    const onOpen = vi.fn();
    wire(() => menu(run, onOpen));
    expect(rightClick().defaultPrevented).toBe(true);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(document.querySelector('[role="menu"][aria-label="row menu"]')).not.toBeNull();
    expect([...document.querySelectorAll('[role="menu"] [data-node]')].map((n) => n.getAttribute('data-node'))).toEqual(['edit', 'delete']);
    (document.querySelector('[data-node="edit"]') as HTMLElement).click();
    flushSync();
    expect(run).toHaveBeenCalledOnce();
    expect(document.querySelector('[role="menu"]'), 'a pick closes the menu').toBeNull();
});

test('a row that declares no menu keeps the browser menu', () => {
    wire(() => null);
    expect(rightClick().defaultPrevented).toBe(false);
    expect(document.querySelector('[role="menu"]')).toBeNull();
});

test('a row draws no menu button of its own', () => {
    wire(() => menu(() => {}));
    expect(row.querySelector('button, [aria-haspopup]')).toBeNull();
});

test('Shift+F10 and the menu key reach the same menu through the row; any other key does not', () => {
    wire(() => menu(() => {}));
    const key = (init: KeyboardEventInit): boolean => forwardMenuKey(new KeyboardEvent('keydown', { cancelable: true, ...init }), row);
    expect(key({ key: 'a' })).toBe(false);
    expect(key({ key: 'F10' })).toBe(false);
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(key({ key: 'F10', shiftKey: true })).toBe(true);
    flushSync();
    expect(document.querySelector('[role="menu"] [data-node="edit"]')).not.toBeNull();
    closeItemMenu();
    expect(key({ key: 'ContextMenu' })).toBe(true);
    expect(forwardMenuKey(new KeyboardEvent('keydown', { key: 'ContextMenu' }), null), 'no row, nothing to open').toBe(false);
});

test('a long press (touch) on a row opens its menu, swallows the lift click, and a scroll or a tap does not', () => {
    vi.useFakeTimers();
    try {
        const run = vi.fn();
        wire(() => menu(run));
        const down = (type = 'touch', x = 5): void => { row.dispatchEvent(Object.assign(new MouseEvent('pointerdown', { bubbles: true, clientX: x, clientY: 5 }), { pointerType: type })); };
        const click = new MouseEvent('click', { bubbles: true, cancelable: true });
        down(); vi.advanceTimersByTime(LONG_PRESS_MS - 100); row.dispatchEvent(new MouseEvent('pointerup', { bubbles: true })); vi.advanceTimersByTime(500);
        expect(document.querySelector('[role="menu"]')).toBeNull();
        down('mouse'); vi.advanceTimersByTime(LONG_PRESS_MS + 10);
        expect(document.querySelector('[role="menu"]')).toBeNull();
        down(); vi.advanceTimersByTime(LONG_PRESS_MS + 10); flushSync();
        expect(document.querySelector('[role="menu"] [data-node="edit"]')).not.toBeNull();
        row.dispatchEvent(click);
        expect(click.defaultPrevented, 'the lift click is swallowed').toBe(true);
    } finally {
        vi.useRealTimers();
    }
});
