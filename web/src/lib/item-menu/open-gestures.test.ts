/** @vitest-environment jsdom */
import { flushSync } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('../companies', () => ({
    companyById: (id: number) => (id === 7 ? { id: 7, name: 'acme', project_count: 2 } : undefined),
    setCompanyColor: vi.fn(async () => ({})),
}));

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

import { headingEvents } from '../sidebar-shell/heading-events';
import { bandEvents } from '../sidebar-shell/row-events';
import { LONG_PRESS_MS } from '../sidebar-shell/row-menu-gestures';
import { closeItemMenu, itemMenuState } from './open.svelte';
import { triggerHtml } from './row-context';
import { installRowMenuOpener } from './row-open';

function companyHeading(): { row: HTMLElement; toggle: HTMLElement; kebab: HTMLElement; detach: () => void } {
    const row = document.createElement('div');
    row.className = 'session-sidebar-group__headerrow';
    row.innerHTML = '<button type="button" data-group-toggle="c:7">acme</button><button type="button" class="session-sidebar-group__menu" data-company-menu="c:7">...</button>';
    document.body.appendChild(row);
    const cleanup = headingEvents()(row) as () => void;
    return {
        row,
        toggle: row.querySelector<HTMLElement>('[data-group-toggle]')!,
        kebab: row.querySelector<HTMLElement>('[data-company-menu]')!,
        detach: () => { cleanup(); row.remove(); },
    };
}

function opened(): { type: string; ids: string[]; anchor: Element; at: unknown } | null {
    const open = itemMenuState.open;
    return open ? { type: open.type, ids: open.nodes.map((n) => n.id), anchor: open.anchor, at: open.at } : null;
}

afterEach(() => { closeItemMenu(); flushSync(); });

describe('a heading opens one menu from every gesture', () => {
    test('kebab click, right-click and Shift+F10 open the same company menu', () => {
        const h = companyHeading();
        h.kebab.click();
        const byKebab = opened();
        closeItemMenu();
        h.toggle.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 12 }));
        const byRightClick = opened();
        closeItemMenu();
        const key = new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true });
        h.toggle.dispatchEvent(key);
        const byShiftF10 = opened();
        closeItemMenu();
        h.toggle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true }));
        const byMenuKey = opened();
        h.detach();

        expect(byKebab, 'the kebab opens a menu').not.toBeNull();
        expect(byKebab!.type).toBe('company');
        expect(byKebab!.ids).toEqual(['rename-company', 'company-color', 'delete-company']);
        for (const [name, got] of [['right-click', byRightClick], ['Shift+F10', byShiftF10], ['menu key', byMenuKey]] as const) {
            expect(got, `${name} opens a menu`).not.toBeNull();
            expect(got!.type, name).toBe(byKebab!.type);
            expect(got!.ids, name).toEqual(byKebab!.ids);
            expect(got!.anchor, `${name} belongs to the same kebab`).toBe(h.kebab);
        }
        expect(byRightClick!.at, 'a right-click hangs at the pointer').toEqual({ x: 40, y: 12 });
        expect(byShiftF10!.at, 'a key hangs from the kebab').toBeNull();
        expect(key.defaultPrevented, 'the key is consumed').toBe(true);
    });

    test('a plain F10 is not a menu request', () => {
        const h = companyHeading();
        h.toggle.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', bubbles: true, cancelable: true }));
        expect(opened()).toBeNull();
        h.detach();
    });
});

function sessionRow(): { name: HTMLElement; kebab: HTMLElement; detach: () => void } {
    const uninstall = installRowMenuOpener();
    const band = document.createElement('div');
    band.innerHTML = '<div class="session-sidebar-row" data-name="cloude_a" tabindex="0"><span class="session-sidebar-row-name">a</span>'
        + triggerHtml({ name: 'cloude_a', label: 'a', kind: 'session', surface: 'sidebar', owned: true, status: 'idle', renameable: true, groupable: true })
        + '</div>';
    document.body.appendChild(band);
    const cleanup = bandEvents()(band) as () => void;
    return {
        name: band.querySelector<HTMLElement>('.session-sidebar-row-name')!,
        kebab: band.querySelector<HTMLElement>('[data-row-menu]')!,
        detach: () => { cleanup(); uninstall(); band.remove(); },
    };
}

function pointer(type: string, pointerType: string): Event {
    const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 5, clientY: 5 });
    Object.defineProperty(e, 'pointerType', { value: pointerType });
    return e;
}

describe('a row opens one menu from every gesture', () => {
    test('kebab click, right-click, Shift+F10, the menu key and a long press open the same session menu', () => {
        vi.useFakeTimers();
        const r = sessionRow();
        try {
            r.kebab.click();
            const byKebab = opened();
            closeItemMenu();
            r.name.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 12 }));
            const byRightClick = opened();
            closeItemMenu();
            const key = new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true });
            r.name.dispatchEvent(key);
            const byShiftF10 = opened();
            closeItemMenu();
            r.name.dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true }));
            const byMenuKey = opened();
            closeItemMenu();
            r.name.dispatchEvent(pointer('pointerdown', 'touch'));
            vi.advanceTimersByTime(LONG_PRESS_MS);
            const byLongPress = opened();

            expect(byKebab, 'the kebab opens a menu').not.toBeNull();
            expect(byKebab!.type).toBe('session');
            expect(byKebab!.ids.length).toBeGreaterThan(3);
            for (const [name, got] of [['right-click', byRightClick], ['Shift+F10', byShiftF10], ['menu key', byMenuKey], ['long press', byLongPress]] as const) {
                expect(got, `${name} opens a menu`).not.toBeNull();
                expect(got!.type, name).toBe('session');
                expect(got!.ids, name).toEqual(byKebab!.ids);
                expect(got!.anchor, `${name} belongs to the same kebab`).toBe(r.kebab);
            }
            expect(byRightClick!.at, 'a right-click hangs at the pointer').toEqual({ x: 40, y: 12 });
            expect(byShiftF10!.at, 'a key hangs from the kebab').toBeNull();
            expect(byLongPress!.at, 'a long press hangs from the kebab').toBeNull();
            expect(key.defaultPrevented, 'the key is consumed').toBe(true);
        } finally {
            r.detach();
            vi.useRealTimers();
        }
    });

    test('a mouse press is never a long press, and a plain F10 is not a menu request', () => {
        vi.useFakeTimers();
        const r = sessionRow();
        try {
            r.name.dispatchEvent(pointer('pointerdown', 'mouse'));
            vi.advanceTimersByTime(LONG_PRESS_MS * 2);
            expect(opened()).toBeNull();
            r.name.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', bubbles: true, cancelable: true }));
            expect(opened()).toBeNull();
        } finally {
            r.detach();
            vi.useRealTimers();
        }
    });
});
