/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { SessionSidebarController } from '../drawer/controller';
import { loadLegacyDrawer, type LegacyWindow } from './legacy-fixture';
import SidebarRow from './SidebarRow.svelte';
import { rowHost } from './row-host';
import { rowMenuBridge } from '../item-menu/row-bridge';
import { buildRowPlan } from './row-plan';
import { activateRow, paintSelection } from './row-activate';
import { onRowKeydown } from './row-reorder';

let w: LegacyWindow;
const PAGE = 'browser:fedcba9876543210';
const BROWSER = 'browser:0123456789abcdef';

function browserRow(name: string, page: boolean): Record<string, unknown> {
    return { name, kind: 'browser', browser_id: name.slice(8), page, label: 'x', url: null, status: page ? 'page' : 'live', is_pinned: false };
}

function draw(r: Record<string, unknown>): { el: HTMLElement; stop: () => void } {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarRow, { target, props: { r: buildRowPlan(r as never, 'compact', 'browsers', undefined, rowHost()) } });
    flushSync();
    return { el: target.querySelector('.session-sidebar-row') as HTMLElement, stop: () => { unmount(app); target.remove(); } };
}

describe('the row icons', () => {
    beforeAll(() => { w = loadLegacyDrawer(); });
    afterEach(() => { document.body.innerHTML = ''; });

    it('a page row and a browser row draw pop out and NO close x', () => {
        for (const [name, page] of [[PAGE, true], [BROWSER, false]] as const) {
            const { el, stop } = draw(browserRow(name, page));
            const keys = Array.from(el.querySelectorAll('[data-browser-row-action]')).map((b) => b.getAttribute('data-browser-row-action'));
            expect(keys).toEqual(['popout']);
            expect(el.querySelector('[data-browser-row-action="popout"]')!.getAttribute('title')).toBe('pop out');
            stop();
        }
    });

    it('the pin sits last before the kebab, after pop out, on both row kinds', () => {
        const tail = (root: Element): string[] =>
            Array.from(root.querySelector('.session-sidebar-row-main')!.children).map((c) => c.className.split(' ')[0] ?? '').slice(-3);
        const want = ['session-sidebar-row-key', 'session-sidebar-row-pin', 'session-row-menu-trigger'];
        for (const [name, page] of [[PAGE, true], [BROWSER, false]] as const) {
            const { el, stop } = draw(browserRow(name, page));
            expect(tail(el)).toEqual(want);
            stop();
        }
    });

    it('a click on the pop out icon runs the kebab\'s own pop out', async () => {
        const calls: string[] = [];
        (globalThis as Record<string, any>).CloudeWeb = {
            ...(globalThis as Record<string, any>).CloudeWeb,
            browsers: { list: () => [], pages: () => [], popOut: async (id: string) => { calls.push(`popOut ${id}`); return true; } },
        };
        const page = draw(browserRow(PAGE, true));
        await w.SessionSidebarBrowsers.onKeyClick(page.el.querySelector('[data-browser-row-action="popout"]'));
        page.stop();
        expect(calls).toEqual([`popOut ${PAGE.slice(8)}`]);
    });
});

describe('shift turns the kebab into a red close x (#1697)', () => {
    beforeAll(() => { w = loadLegacyDrawer(); });
    afterEach(() => {
        window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
        flushSync();
        delete (globalThis as Record<string, any>).CloudeWeb;
        document.body.innerHTML = '';
    });

    const shift = (down: boolean): void => {
        window.dispatchEvent(new KeyboardEvent(down ? 'keydown' : 'keyup', { key: 'Shift', shiftKey: down }));
        flushSync();
    };
    const closeKey = (el: HTMLElement): HTMLElement | null => el.querySelector('[data-browser-row-action="close"]');

    it('draws the x only while Shift is held, as a sibling after the kebab, with the catalog label, and blur restores', () => {
        for (const [name, page, label] of [[PAGE, true, 'close page'], [BROWSER, false, 'close proxy browser']] as const) {
            const { el, stop } = draw(browserRow(name, page));
            expect(closeKey(el)).toBeNull();
            expect(el.hasAttribute('data-shift-close')).toBe(false);

            shift(true);
            const x = closeKey(el)!;
            expect(x).not.toBeNull();
            expect(el.getAttribute('data-shift-close')).toBe('1');
            expect(x.getAttribute('aria-label')).toBe(label);
            expect(x.getAttribute('title')).toBe(label);
            const trigger = el.querySelector('[data-row-menu]')!;
            expect(trigger).not.toBeNull();
            expect(trigger.contains(x)).toBe(false);
            expect(x.closest('.session-sidebar-row-shift-close')!.previousElementSibling).toBe(trigger);

            shift(false);
            expect(closeKey(el)).toBeNull();
            expect(el.hasAttribute('data-shift-close')).toBe(false);

            shift(true);
            window.dispatchEvent(new Event('blur'));
            flushSync();
            expect(closeKey(el)).toBeNull();
            stop();
        }
    });

    it('while Shift is held EVERY browser and page row shows its x at once, and releasing Shift takes every one away', () => {
        const rows = [draw(browserRow(PAGE, true)), draw(browserRow(BROWSER, false)), draw(browserRow('browser:00000000000000aa', false))];
        expect(rows.map(({ el }) => closeKey(el))).toEqual([null, null, null]);

        shift(true);
        for (const { el } of rows) {
            expect(el.getAttribute('data-shift-close')).toBe('1');
            expect(closeKey(el)).not.toBeNull();
            expect(closeKey(el)!.closest('.session-sidebar-row')).toBe(el);
        }
        expect(document.querySelectorAll('[data-browser-row-action="close"]')).toHaveLength(3);

        shift(false);
        expect(document.querySelectorAll('[data-browser-row-action="close"]')).toHaveLength(0);
        expect(document.querySelectorAll('[data-shift-close]')).toHaveLength(0);
        rows.forEach(({ stop }) => stop());
    });

    it('a click on the x runs the kebab\'s close: a page at once, a browser after its confirm', async () => {
        const calls: string[] = [];
        (globalThis as Record<string, any>).CloudeWeb = {
            browsers: { list: () => [], pages: () => [], close: async (id: string) => { calls.push(`close ${id}`); return true; } },
            rowMenu: rowMenuBridge,
        };
        const confirms: string[] = [];
        const app = (w as unknown as Record<string, any>).App;
        (w as unknown as Record<string, any>).App = {
            ...app,
            showConfirmModal: async (title: string, subject: string) => { confirms.push(`${title} ${subject}`); return true; },
        };
        try {
            const page = draw(browserRow(PAGE, true));
            const browser = draw(browserRow(BROWSER, false));
            shift(true);
            await w.SessionSidebarBrowsers.onKeyClick(closeKey(page.el));
            expect(calls).toEqual([`close ${PAGE.slice(8)}`]);
            expect(confirms).toEqual([]);

            await w.SessionSidebarBrowsers.onKeyClick(closeKey(browser.el));
            page.stop();
            browser.stop();
            expect(confirms).toEqual(['close this proxy browser? x']);
            expect(calls).toEqual([`close ${PAGE.slice(8)}`, `close ${BROWSER.slice(8)}`]);
        } finally {
            (w as unknown as Record<string, any>).App = app;
        }
    });
});

describe('the red close x from the keyboard (#1697)', () => {
    beforeAll(() => { w = loadLegacyDrawer(); });
    afterEach(() => {
        window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
        flushSync();
        delete (globalThis as Record<string, any>).SessionSidebar;
        document.body.innerHTML = '';
    });

    function recordingDrawer(): string[] {
        const reads: string[] = [];
        (globalThis as Record<string, any>).SessionSidebar = new Proxy({}, {
            get: (_t, key) => { reads.push(String(key)); return undefined; },
        });
        return reads;
    }

    function press(row: HTMLElement, key: string, shiftKey: boolean): KeyboardEvent {
        const e = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true });
        row.addEventListener('keydown', (ev) => onRowKeydown(ev, row), { once: true });
        row.dispatchEvent(e);
        return e;
    }

    it('shift with enter, space or delete on the focused row presses the x and never opens the row', () => {
        const bridge = w.SessionSidebarBrowsers as Record<string, any>;
        const real = bridge.onKeyClick;
        const pressed: (string | null)[] = [];
        bridge.onKeyClick = (el: Element) => { pressed.push(el.getAttribute('data-browser-row-action')); return Promise.resolve(); };
        try {
            const { el, stop } = draw(browserRow(PAGE, true));
            const reads = recordingDrawer();
            window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
            flushSync();
            for (const key of ['Enter', ' ', 'Delete']) {
                const e = press(el, key, true);
                expect(e.defaultPrevented).toBe(true);
            }
            expect(pressed).toEqual(['close', 'close', 'close']);
            expect(reads).toEqual([]);

            window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
            flushSync();
            press(el, 'Enter', false);
            expect(pressed).toEqual(['close', 'close', 'close']);
            expect(reads.length).toBeGreaterThan(0);
            stop();
        } finally {
            bridge.onKeyClick = real;
        }
    });
});

describe('selection while a page fills the main section', () => {
    let showing: string | null;
    beforeEach(() => {
        showing = null;
        const g = globalThis as Record<string, any>;
        g.CloudeWeb = { browsers: { showing: () => showing, dismiss: vi.fn(() => { showing = null; return true; }) } };
    });
    afterEach(() => { delete (globalThis as Record<string, any>).CloudeWeb; document.body.innerHTML = ''; });

    function listOf(names: string[]): HTMLElement {
        const list = document.createElement('div');
        list.innerHTML = names.map((n) => `<div class="session-sidebar-row" data-name="${n}" aria-selected="false"></div>`).join('');
        document.body.appendChild(list);
        return list;
    }
    const selected = (list: HTMLElement): string[] =>
        Array.from(list.querySelectorAll('[aria-selected="true"]')).map((e) => (e as HTMLElement).dataset.name!);

    it('the page row is the selected row (paint and the controller\'s data-active), the session under it is not, and it moves', () => {
        const list = listOf(['cloude_a', PAGE, BROWSER]);
        const ctrl = new SessionSidebarController();
        (ctrl as unknown as Record<string, unknown>)._activeTmuxName = 'cloude_a';
        const ro = ctrl as unknown as { listEl: HTMLElement; _pendingSelection: null };
        ro.listEl = list;
        paintSelection(ro as never);
        expect(selected(list)).toEqual(['cloude_a']);

        showing = PAGE.slice(8);
        paintSelection(ro as never);
        expect(selected(list)).toEqual([PAGE]);
        expect(ctrl._isThisTab(PAGE)).toBe(true);
        expect(ctrl._isThisTab('cloude_a')).toBe(false);

        showing = BROWSER.slice(8);
        paintSelection(ro as never);
        expect(selected(list)).toEqual([BROWSER]);
        expect(ctrl._isThisTab(PAGE)).toBe(false);

        showing = null;
        paintSelection(ro as never);
        expect(selected(list)).toEqual(['cloude_a']);
        expect(ctrl._isThisTab('cloude_a')).toBe(true);
    });

    it('picking the session the page covers leaves the page instead of doing nothing', async () => {
        const list = listOf(['cloude_a']);
        showing = PAGE.slice(8);
        const closed = vi.fn();
        const ctrl = { listEl: list, _activeTmuxName: 'cloude_a', _pendingSelection: null, _closeAfterSwitch: closed };
        await activateRow(ctrl as never, list.querySelector('.session-sidebar-row')!);
        expect((globalThis as Record<string, any>).CloudeWeb.browsers.dismiss).toHaveBeenCalledTimes(1);
        expect(closed).toHaveBeenCalled();
    });
});
