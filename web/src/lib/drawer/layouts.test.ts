/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import * as GroupStore from './group-store';
import * as Model from './layouts-model';
import { menuContext, rowParts } from './layouts-row-html';
const pinning = vi.hoisted(() => ({ toggled: [] as string[] }));
vi.mock('../sidebar-shell/row-reorder', () => ({
    togglePinRow: (name: string) => { pinning.toggled.push(name); return true; },
}));
import { runMenuItem } from './layouts-menu';
import { reorderedUuids, wireLayoutsDrag } from './layouts-drag';

const LAYOUTS = [
    { layout_uuid: 'L2', name: 'second', colour: 'teal', gradient: null, animation: 'shimmer', created_at: '2026-01-02T00:00:00Z', members: [{ session_uuid: 's1' }, { session_uuid: 'gone' }] },
    { layout_uuid: 'L1', name: 'first', colour: 'indigo', gradient: null, animation: 'none', created_at: '2026-01-01T00:00:00Z', members: [] },
];

function page(extra: Record<string, unknown> = {}, list = LAYOUTS) {
    const bridge = { list: () => list, rename: vi.fn(async () => ({})), delete: vi.fn(async () => {}), reorder: vi.fn(async () => ({})) };
    setDrawerEnv({ CloudeWeb: { layouts: bridge, rowMenu: { triggerHtml: (c: { name: string }) => `<i data-menu="${c.name}"></i>` } }, ...extra });
    return bridge;
}

beforeEach(() => {
    localStorage.clear();
    const g = globalThis as { CSS?: { escape?(v: string): string } };
    if (!g.CSS || typeof g.CSS.escape !== 'function') g.CSS = { ...(g.CSS || {}), escape: (v: string) => String(v) };
});
afterEach(() => { setDrawerEnv(null); GroupStore.reset(); document.body.innerHTML = ''; });

describe('rows and the band', () => {
    it('lists rows in the bridge order and resolves members by session_uuid, dropping the missing', () => {
        page();
        const out = Model.rows([{ session_uuid: 's1', name: 'cloude_a', label: 'Alpha' }]);
        expect(out.map((r) => r.name)).toEqual(['layout:L2', 'layout:L1']);
        expect(out[0]?.member_count).toBe(2);
        expect(out[0]?._members).toHaveLength(1);
        expect(out[0]?.member_names).toEqual(['Alpha']);
    });
    it('the band takes its order from the bridge, not from allRows, and is null with none', () => {
        page();
        const all = Model.rows([]).reverse();
        expect(Model.bandRows(all)?.rows.map((r) => r.layout_uuid)).toEqual(['L2', 'L1']);
        page({}, []);
        expect(Model.bandRows([])).toBeNull();
    });
    it('answers nothing before the bridge exists', () => {
        setDrawerEnv({});
        expect(Model.rows([])).toEqual([]);
        expect(Model.bandRows([])).toBeNull();
        expect(Model.memberUuids().size).toBe(0);
    });
    it('names and ids round trip; only the LAYOUTS band expands, and a Layout defaults collapsed', () => {
        page();
        const row = Model.rows([{ session_uuid: 's1', name: 'a' }])[0] as Model.LayoutRow;
        expect(Model.isLayoutName('layout:x')).toBe(true);
        expect(Model.idOf('layout:x')).toBe('x');
        expect(Model.idOf('cloude_x')).toBe('');
        expect(Model.memberBody(row, 'pinned')).toBeNull();
        expect(Model.memberBody(row, 'layouts')?.members).toEqual([]);
    });
});

describe('the row parts', () => {
    it('stamps the colour on the row alone, with the shimmer windows, and the members subtitle key', () => {
        page();
        const row = Model.rows([])[0] as Model.LayoutRow;
        const parts = rowParts(row, 'layouts');
        expect(parts.attrs['data-layout-colour']).toBe('teal');
        expect(parts.attrs['data-layout-anim']).toBe('shimmer');
        expect(parts.attrs['data-kind']).toBe('layout');
        expect(parts.attrs['data-band']).toBe('layouts');
        expect(parts.name.fxHtml.match(/<i data-t=/g)).toHaveLength(24);
        expect(parts.toggle?.attrs.class).toBe('session-sidebar-layout__toggle');
        expect(parts.pin).toEqual({ name: 'layout:L2', pinned: false });
        expect(parts.toggle?.svg).toContain('session-sidebar-group__chevron');
        expect(parts.toggle?.svg).toContain('M4 2l4 4-4 4');
    });
    it('a copy under PINNED has no fold toggle, and an indigo default paints no colour attribute', () => {
        page();
        const row = Model.rows([])[1] as Model.LayoutRow;
        const parts = rowParts(row, 'pinned');
        expect(parts.toggle).toBeNull();
        expect(parts.attrs['data-layout-colour']).toBeUndefined();
    });
    it('the menu context files under a real group only', () => {
        page();
        GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'g1', name: 'g', position: 0, members: [], member_session_uuids: [], colour: 'teal', gradient: null, animation: 'none', icon: null }] });
        const row = Model.rows([])[0] as Model.LayoutRow;
        expect(menuContext(row, 'g:g1').groupUuid).toBe('g1');
        expect(menuContext(row, 'g:deleted').groupUuid).toBe('');
        expect(menuContext(row, 'layouts').groupUuid).toBe('');
        expect(menuContext(row, 'layouts').kind).toBe('layout');
    });
});

describe('menu items', () => {
    it('remove confirms, then deletes by the uuid in ctx.name (never ctx.layoutUuid)', async () => {
        const bridge = page({ App: { showConfirmModal: vi.fn(async () => true) } });
        await runMenuItem('close', { name: 'layout:L2', label: 'second' });
        expect(bridge.delete).toHaveBeenCalledWith('L2');
    });
    it('a declined confirm deletes nothing', async () => {
        const bridge = page({ App: { showConfirmModal: vi.fn(async () => false) } });
        await runMenuItem('close', { name: 'layout:L2' });
        expect(bridge.delete).not.toHaveBeenCalled();
    });
    it('pin toggles through the shell reorder module; an item that is not a Layout answers null', async () => {
        pinning.toggled.length = 0;
        page();
        await runMenuItem('pin', { name: 'layout:L2' });
        expect(pinning.toggled).toEqual(['layout:L2']);
        expect(runMenuItem('rename', { name: 'layout:L2' })).toBeNull();
    });
    it('blueprints are on only once the bundle publishes fromLayout', () => {
        page();
        expect(Model.blueprintsEnabled()).toBe(false);
        page({ CloudeWeb: { layouts: { list: () => [] }, blueprints: { fromLayout: () => {} } } });
        expect(Model.blueprintsEnabled()).toBe(true);
    });
});

describe('activate and rename', () => {
    it('a Layout click opens in place and answers true; any other name answers false', () => {
        const openLayout = vi.fn();
        page({ CloudeWeb: { layouts: { list: () => [] }, layoutPage: { openLayout } } });
        expect(Model.activate(null, 'layout:L1')).toBe(true);
        expect(openLayout).toHaveBeenCalledWith('L1');
        expect(Model.activate(null, 'cloude_x')).toBe(false);
    });
    it('rename rejects when the module is not loaded', async () => {
        setDrawerEnv({});
        await expect(Model.rename('L1', 'x')).rejects.toThrow('not loaded');
    });
});

describe('reorderedUuids', () => {
    it('moves before or after the row dropped on', () => {
        expect(reorderedUuids(['a', 'b', 'c'], 'a', 'c', false)).toEqual(['b', 'c', 'a']);
        expect(reorderedUuids(['a', 'b', 'c'], 'c', 'a', true)).toEqual(['c', 'a', 'b']);
    });
});


describe('the section drag', () => {
    function dragEvent(type: string, store: Map<string, string>, clientY = 0): Event {
        const e = new Event(type, { bubbles: true, cancelable: true });
        Object.defineProperty(e, 'dataTransfer', {
            value: { effectAllowed: '', setData: (k: string, v: string) => store.set(k, v), getData: (k: string) => store.get(k) ?? '' },
        });
        Object.defineProperty(e, 'clientY', { value: clientY });
        return e;
    }

    it('dragstart on one Layout row then drop on another writes the whole new order through reorder', async () => {
        const bridge = page();
        wireLayoutsDrag();
        document.body.innerHTML = '<div data-kind="layout" data-layout-uuid="L2" id="a"></div><div data-kind="layout" data-layout-uuid="L1" id="b"></div>';
        const store = new Map<string, string>();
        document.getElementById('a')?.dispatchEvent(dragEvent('dragstart', store));
        document.getElementById('b')?.dispatchEvent(dragEvent('drop', store, 5));
        await vi.waitFor(() => expect(bridge.reorder).toHaveBeenCalledWith(['L1', 'L2']));
    });

    it('a drop with no drag in flight, or on a non-Layout, reorders nothing', async () => {
        const bridge = page();
        wireLayoutsDrag();
        document.body.innerHTML = '<div data-kind="layout" data-layout-uuid="L1" id="b"></div><p id="p"></p>';
        const store = new Map<string, string>([['text/plain', 'L2']]);
        document.getElementById('b')?.dispatchEvent(dragEvent('drop', store));
        document.getElementById('p')?.dispatchEvent(dragEvent('dragstart', store));
        document.getElementById('p')?.dispatchEvent(dragEvent('drop', store));
        await Promise.resolve();
        expect(bridge.reorder).not.toHaveBeenCalled();
    });
});

describe('blueprint items and a failed remove', () => {
    it('save as blueprint names it through the prompt, posts it, and announces the result', async () => {
        const fromLayout = vi.fn(async () => ({ ok: true, name: 'mine' }));
        const live = document.createElement('div');
        live.id = 'session-sidebar-live';
        document.body.appendChild(live);
        const open = vi.fn(async (_opts: Record<string, string>) => ' mine ');
        page({ TextPromptModal: { open },
            CloudeWeb: { layouts: { list: () => [] }, blueprints: { fromLayout } } });
        await runMenuItem('save-blueprint', { name: 'layout:L2', label: 'second' });
        expect(open.mock.calls[0]?.[0]).toMatchObject({ defaultValue: 'second' });
        expect(fromLayout).toHaveBeenCalledWith('L2', 'mine');
        expect(live.textContent).toContain('mine');
        live.remove();
    });

    it('a cancelled prompt posts nothing; a refused save is shown with an alert', async () => {
        const fromLayout = vi.fn(async () => ({ ok: false, reason: 'name taken' }));
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        page({ TextPromptModal: { open: vi.fn(async () => null) }, CloudeWeb: { layouts: { list: () => [] }, blueprints: { fromLayout } } });
        await runMenuItem('save-blueprint', { name: 'layout:L2' });
        expect(fromLayout).not.toHaveBeenCalled();
        page({ TextPromptModal: { open: vi.fn(async () => 'x') }, CloudeWeb: { layouts: { list: () => [] }, blueprints: { fromLayout } } });
        await runMenuItem('save-blueprint', { name: 'layout:L2' });
        expect(String(alert.mock.calls[0]?.[0])).toContain('name taken');
    });

    it('load blueprint opens the picker beside the row kebab, or the screen without one', async () => {
        const kebab = document.createElement('button');
        const row = document.createElement('div');
        row.className = 'session-sidebar-row';
        row.setAttribute('data-name', 'layout:L2');
        kebab.setAttribute('data-row-menu', '');
        row.appendChild(kebab);
        document.body.appendChild(row);
        const openBlueprintPicker = vi.fn();
        const openBlueprintsScreen = vi.fn();
        page({ CloudeWeb: { layouts: { list: () => [] }, openBlueprintPicker, openBlueprintsScreen } });
        await runMenuItem('load-blueprint', { name: 'layout:L2' });
        expect(openBlueprintPicker).toHaveBeenCalledWith(kebab);
        row.remove();
        page({ CloudeWeb: { layouts: { list: () => [] }, openBlueprintPicker, openBlueprintsScreen } });
        await runMenuItem('load-blueprint', { name: 'layout:L2' });
        expect(openBlueprintsScreen).toHaveBeenCalledTimes(1);
    });

    it('a remove the bridge refuses is reported with an alert naming the reason', async () => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        vi.spyOn(console, 'error').mockImplementation(() => {});
        const bridge = page({ App: { showConfirmModal: vi.fn(async () => true) } });
        bridge.delete.mockRejectedValueOnce(new Error('server said no'));
        await runMenuItem('close', { name: 'layout:L2', label: 'second' });
        expect(String(alert.mock.calls[0]?.[0])).toContain('server said no');
    });
});
