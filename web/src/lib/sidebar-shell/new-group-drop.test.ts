/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const flow = vi.hoisted(() => ({ create: vi.fn(async (_name: string | null, _onFiled?: () => void) => {}), commit: vi.fn(async () => true) }));
vi.mock('./group-assign', () => ({ createGroupThenAssign: flow.create, commitAssignment: flow.commit }));
vi.mock('./pack-source.svelte', () => ({ packSource: () => [{ install_id: 'self', label: 'this one', is_self: true }], watchPack: () => {} }));

import * as GroupStore from '../drawer/group-store';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { setCountFilter } from '../drawer/count-filter.svelte';
import { buildListPlan, type PaintInput } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';
import { onRowPointerDown } from './row-drag';
import { current as arrangementNow, save as saveArrangement } from '../drawer/store';

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;

const stubs = (): LegacyDrawer => ({ projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null } });
const rows: SidebarRow[] = [{ name: 'a', project_id: 1, project_name: 'one' }, { name: 'b', project_id: 1, project_name: 'one' }];
const paint = (dragging: boolean): PaintInput => ({
    rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: { dragging },
});

beforeEach(() => {
    setCountFilter(null);
    localStorage.clear();
    Store.load();
    setQuery('');
    flow.create.mockClear();
    flow.commit.mockClear();
});

describe('the plan', () => {
    it('draws the target while a row drag is in flight, even with no group yet', () => {
        GroupStore.apply({ status: 'ok', groups: [] });
        const plan = buildListPlan(stubs(), paint(true))!;
        expect(plan.parts.filter((p) => p.type === 'newgroup').map((p) => p.key)).toEqual(['newgroup']);
    });

    it('sits right after the groups block when groups exist', () => {
        GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'x', name: 'x crew', position: 0, members: ['b'] }] });
        const types = buildListPlan(stubs(), paint(true))!.parts.map((p) => p.type);
        expect(types[types.indexOf('groups') + 1]).toBe('newgroup');
    });

    it('draws nothing while the group model is unavailable: nothing could be created', () => {
        GroupStore.apply({ status: 'unavailable', detail: 'down' });
        expect(buildListPlan(stubs(), paint(true))!.parts.some((p) => p.type === 'newgroup')).toBe(false);
    });

    it('draws nothing when no drag is in flight', () => {
        GroupStore.apply({ status: 'ok', groups: [] });
        expect(buildListPlan(stubs(), paint(false))!.parts.some((p) => p.type === 'newgroup')).toBe(false);
    });
});

describe('the drop', () => {
    let list: HTMLElement;

    function box(el: Element, top: number, bottom: number): void {
        el.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 300, width: 300, height: bottom - top, x: 0, y: top, toJSON() {} });
    }

    function draw(): HTMLElement {
        list.innerHTML = '<div class="session-sidebar-group" data-group="p:1"><div class="session-sidebar-row" data-name="b" data-band="p:1"><span></span></div></div><div class="session-sidebar-newgroup" data-newgroup="1"></div>';
        box(list.querySelector('.session-sidebar-group')!, 0, 40);
        box(list.querySelector('.session-sidebar-row')!, 0, 40);
        box(list.querySelector('[data-newgroup]')!, 60, 90);
        return list.querySelector('.session-sidebar-row')!;
    }

    function pointer(type: string, y: number, x = 100): MouseEvent {
        const e = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true, cancelable: true });
        Object.assign(e, { pointerId: 1, pointerType: 'mouse' });
        return e;
    }

    function dragTo(y: number): void {
        const row = draw();
        const down = pointer('pointerdown', 10);
        Object.defineProperty(down, 'target', { value: row });
        onRowPointerDown(down as PointerEvent);
        document.dispatchEvent(pointer('pointermove', y));
        document.dispatchEvent(pointer('pointerup', y));
    }

    beforeEach(() => {
        Store.load();
        GroupStore.apply({ status: 'ok', groups: [] });
        list = document.createElement('div');
        document.body.append(list);
        win.SessionSidebar = { listEl: list, setDragging: vi.fn(), repaint: () => {} };
        win.CloudeWeb = undefined;
    });

    afterEach(() => {
        list.remove();
        delete win.SessionSidebar;
    });

    it('a drop on the target asks for a name for that session', () => {
        dragTo(75);
        expect(flow.create).toHaveBeenCalledTimes(1);
        expect(flow.create).toHaveBeenCalledWith('b', expect.any(Function));
        expect(flow.commit).not.toHaveBeenCalled();
    });

    it('marks the target while the pointer is over it', () => {
        const row = draw();
        const down = pointer('pointerdown', 10);
        Object.defineProperty(down, 'target', { value: row });
        onRowPointerDown(down as PointerEvent);
        document.dispatchEvent(pointer('pointermove', 75));
        expect(list.querySelector<HTMLElement>('[data-newgroup]')!.dataset['over']).toBe('1');
        document.dispatchEvent(pointer('pointermove', 20));
        expect(list.querySelector<HTMLElement>('[data-newgroup]')!.dataset['over']).toBe('0');
        document.dispatchEvent(pointer('pointerup', 20));
    });

    it('a drop elsewhere, or below every band, never asks for a name', () => {
        dragTo(20);
        dragTo(500);
        expect(flow.create).not.toHaveBeenCalled();
    });

    function dragHold(y: number): void {
        const row = draw();
        const down = pointer('pointerdown', 10);
        Object.defineProperty(down, 'target', { value: row });
        onRowPointerDown(down as PointerEvent);
        document.dispatchEvent(pointer('pointermove', y));
    }

    it('a drop after crossing another band puts the group, pins and order back to where the drag began', () => {
        saveArrangement(['b'], ['b', 'a'], undefined, undefined, {});
        GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'x', name: 'x crew', position: 0, members: [] }] });
        const before = JSON.stringify(arrangementNow());
        list.innerHTML = '<div class="session-sidebar-group" data-group="p:1"><div class="session-sidebar-row" data-name="b" data-band="p:1"></div><div class="session-sidebar-row" data-name="a" data-band="p:1"></div></div>'
            + '<div class="session-sidebar-group" data-group="g:x"><div class="session-sidebar-row" data-name="c" data-band="g:x"></div></div><div class="session-sidebar-newgroup" data-newgroup="1"></div>';
        const [p1, gx] = Array.from(list.querySelectorAll('.session-sidebar-group'));
        box(p1!, 0, 40);
        box(gx!, 40, 80);
        const [rb, ra, rc] = Array.from(list.querySelectorAll('.session-sidebar-row'));
        box(rb!, 0, 20);
        box(ra!, 20, 40);
        box(rc!, 40, 80);
        box(list.querySelector('[data-newgroup]')!, 100, 130);
        const down = pointer('pointerdown', 10);
        Object.defineProperty(down, 'target', { value: rb });
        onRowPointerDown(down as PointerEvent);
        document.dispatchEvent(pointer('pointermove', 60));
        expect(GroupStore.groupOf('b')).toBe('x');
        expect(JSON.stringify(arrangementNow())).not.toBe(before);
        document.dispatchEvent(pointer('pointermove', 115));
        document.dispatchEvent(pointer('pointerup', 115));
        expect(flow.create).toHaveBeenCalledWith('b', expect.any(Function));
        expect(GroupStore.groupOf('b')).toBeNull();
        expect(JSON.stringify(arrangementNow())).toBe(before);
    });

    it('a cancelled gesture over the target never asks for a name', () => {
        dragHold(75);
        document.dispatchEvent(pointer('pointercancel', 75));
        expect(flow.create).not.toHaveBeenCalled();
    });

    it('a drag the tab strips take over never asks for a name, even after hovering the target', () => {
        const begin = vi.fn(() => true);
        win.CloudeWeb = { tabDrag: { begin } };
        dragHold(75);
        list.getBoundingClientRect = () => ({ left: 0, right: 300, top: 0, bottom: 400, width: 300, height: 400, x: 0, y: 0, toJSON() {} });
        document.dispatchEvent(pointer('pointermove', 75, 900));
        expect(begin).toHaveBeenCalled();
        expect(flow.create).not.toHaveBeenCalled();
    });

    it('a pinned row is unpinned once the new group has it, so it shows in the group and not still in PINNED', () => {
        saveArrangement(['b'], ['b'], undefined, undefined, {});
        dragHold(75);
        document.dispatchEvent(pointer('pointerup', 75));
        const onFiled = flow.create.mock.calls[0]?.[1] as (() => void) | undefined;
        expect(arrangementNow().pinned).toEqual(['b']);
        const repaints = vi.fn();
        win.SessionSidebar = { listEl: list, setDragging: vi.fn(), repaint: repaints };
        onFiled?.();
        expect(arrangementNow().pinned).toEqual([]);
        expect(repaints).toHaveBeenCalled();
    });
});
