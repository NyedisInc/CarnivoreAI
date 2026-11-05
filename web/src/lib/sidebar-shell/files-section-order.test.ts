/** @vitest-environment jsdom */
import { beforeAll, beforeEach, expect, it } from 'vitest';
import { loadRowInteractions } from './row-interaction-fixture';
import { play } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';
import { fromServer, toServer } from '../drawer/sync';

let w: Record<string, any>;

const HEAD_PX = 100;

beforeAll(() => {
    w = loadRowInteractions(sidebarShell);
    const rowRect = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (this: Element): DOMRect {
        if (this.classList.contains('session-sidebar-group__headerrow')) {
            const at = Array.from(document.querySelectorAll('#session-sidebar-list .session-sidebar-group__headerrow')).indexOf(this);
            const top = at * HEAD_PX;
            return { top, bottom: top + 20, height: 20, left: 0, right: 300, width: 300, x: 0, y: top, toJSON() {} } as DOMRect;
        }
        return rowRect.call(this);
    };
});

beforeEach(() => { w.SessionSidebarStore.save([], [], [], {}, {}, undefined, null); });

function file(): Record<string, unknown> {
    return {
        name: 'browser:0000000000000001', kind: 'browser', browser_id: '0000000000000001', file: true, file_kind: 'file', path: 'a.md',
        label: 'a.md', dirty: false, url: null, status: 'file', created_at_epoch: 1, last_work_at: null,
        project_id: null, project_name: null, working_dir: null,
    };
}

function drawn(): string[] {
    return Array.from(document.querySelectorAll<HTMLElement>('#session-sidebar-list [data-section]')).map((e) => e.dataset.section || '');
}

const HEAD = (id: string): string => `[data-section="${id}"] > .session-sidebar-group__headerrow`;

async function dragTo(g: { el(s: string): HTMLElement; press(s: string): { release(): Promise<void> } }, from: string, y: number): Promise<void> {
    const start = g.el(from).getBoundingClientRect().top + 2;
    g.el(from).dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: 10, clientY: start, pointerId: 1, pointerType: 'mouse', button: 0 }));
    for (let at = start; Math.abs(y - at) >= 4; at += y > at ? 4 : -4) {
        document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, cancelable: true, clientX: 10, clientY: at, pointerId: 1, pointerType: 'mouse', button: 0 }));
    }
    document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, cancelable: true, clientX: 10, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0 }));
    document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, clientX: 10, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0 }));
    await new Promise((r) => setTimeout(r, 0));
}

function roundTrip(): string[] {
    const local = w.SessionSidebarArrangement.current();
    const shared = toServer(local, [], null);
    return (fromServer(shared, local, []).sections ?? []) as string[];
}

it('the FILES heading drags above BROWSERS and the order survives a refresh and the shared round trip', async () => {
    await play(w, async (g) => {
        const ctrl = w.SessionSidebar;
        ctrl._rows = [...ctrl._rows, file()];
        ctrl.repaint();
        const before = drawn();
        expect(before.indexOf('files')).toBeGreaterThan(-1);
        await dragTo(g, HEAD('files'), g.el(HEAD('browsers')).getBoundingClientRect().top + 5);
        const after = drawn();
        expect(after.indexOf('files')).toBe(after.indexOf('browsers') - 1);
        ctrl._rows = [...ctrl._rows];
        ctrl.repaint();
        expect(drawn()).toEqual(after);
        expect(roundTrip().indexOf('files')).toBe(roundTrip().indexOf('browsers') - 1);
    });
});

it('another section drops below FILES and stays there', async () => {
    await play(w, async (g) => {
        const ctrl = w.SessionSidebar;
        ctrl._rows = [...ctrl._rows, file()];
        ctrl.repaint();
        expect(drawn().indexOf('terminals')).toBeLessThan(drawn().indexOf('files'));
        await dragTo(g, HEAD('terminals'), 99 * HEAD_PX);
        const after = drawn();
        expect(after.indexOf('terminals')).toBeGreaterThan(after.indexOf('files'));
        ctrl.repaint();
        expect(drawn()).toEqual(after);
        const stored = roundTrip();
        expect(stored.indexOf('terminals')).toBeGreaterThan(stored.indexOf('files'));
    });
});
