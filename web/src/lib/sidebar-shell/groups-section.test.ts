/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import * as GroupStore from '../drawer/group-store';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { isBandOrderKey, isFoldKey } from '../drawer/store-keys';
import { buildListPlan, type GroupsPlan, type ListPlan, type PaintInput } from './plan';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import { unmountPanel } from '../mount';
import { sidebarShell } from './shell.svelte';
import type { LegacyDrawer, SidebarRow } from './legacy';

vi.mock('./pack-source.svelte', () => ({ packSource: () => [], watchPack: () => {} }));

function stubs(): LegacyDrawer {
    return {
        groups: {},
        projectHeader: {
            ledHtml: () => '',
            iconHtml: (n) => (n ? `<i ${n}>` : ''),
            iconForBand: () => null,
        },
    };
}

function input(rows: SidebarRow[], over: Partial<PaintInput> = {}): PaintInput {
    return { rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: {}, ...over };
}

const A: SidebarRow = { name: 'a', is_pinned: true, project_id: 1, project_name: 'one' };
const B: SidebarRow = { name: 'b', project_id: 1, project_name: 'one' };
const C: SidebarRow = { name: 'c', project_id: 1, project_name: 'one' };
const T: SidebarRow = { name: 't', agent_family: 'shell', project_id: null };

const GROUPS = [
    { group_uuid: 'x', name: 'x crew', position: 0, members: ['b'] },
    { group_uuid: 'y', name: 'y crew', position: 1, members: ['c'] },
    { group_uuid: 'z', name: 'z crew', position: 2, members: [] },
];

function groupsPart(plan: ListPlan): GroupsPlan | undefined {
    const part = plan.parts.find((p) => p.type === 'groups');
    return part?.type === 'groups' ? part : undefined;
}

function planWith(collapsed: string[], over: Partial<PaintInput> = {}): ListPlan {
    return buildListPlan(stubs(), input([A, B, C, T], { arrangement: { ...Store.current(), collapsed }, ...over }))!;
}

beforeEach(() => {
    localStorage.clear();
    Store.load();
    setQuery('');
    GroupStore.apply({ status: 'ok', groups: GROUPS });
});

describe('the GROUPS part of the plan', () => {
    it('holds every group that draws, in the stored group order, under one heading', () => {
        const part = groupsPart(planWith([]))!;
        expect(part.key).toBe('groups');
        expect(part.heading).toMatchObject({ key: 'groups', label: 'groups', bandKind: 'reserved', expanded: true });
        expect(part.sections.map((s) => s.key)).toEqual(['g:x', 'g:y']);
        expect(planWith([]).parts.filter((p) => p.key.startsWith('g:'))).toEqual([]);
    });

    it('folding GROUPS hides every group at once and leaves each group its own fold', () => {
        const shut = groupsPart(planWith(['groups']))!;
        expect(shut.open).toBe(false);
        expect(shut.heading).toMatchObject({ expanded: false, label: 'groups' });
        expect(shut.sections).toEqual([]);
        const own = groupsPart(planWith(['g:x']))!;
        expect(own.open).toBe(true);
        expect(own.sections.find((s) => s.key === 'g:x')).toMatchObject({ collapsed: true, rows: [], count: 1 });
        expect(own.sections.find((s) => s.key === 'g:y')!.rows.length).toBe(1);
    });

    it('a row drag keeps a folded GROUPS open, so every group stays a drop target', () => {
        const part = groupsPart(planWith(['groups'], { opts: { dragging: true } }))!;
        expect(part.open).toBe(true);
        expect(part.sections.map((s) => s.key)).toEqual(['g:x', 'g:y', 'g:z']);
    });

    it('draws no GROUPS heading when no group exists or none holds a row', () => {
        GroupStore.apply({ status: 'ok', groups: [] });
        expect(groupsPart(planWith([]))).toBeUndefined();
        GroupStore.apply({ status: 'ok', groups: [GROUPS[2]!] });
        expect(groupsPart(planWith([]))).toBeUndefined();
    });

    it('a search narrows the groups under it and drops GROUPS when nothing matches', () => {
        setQuery('b');
        const hit = groupsPart(planWith([], { opts: { query: 'b' } }));
        expect(hit?.sections.map((s) => s.key)).toEqual(['g:x']);
        setQuery('zzz-nothing');
        expect(groupsPart(planWith([], { opts: { query: 'zzz-nothing' } }))).toBeUndefined();
    });

    it('the stored section order moves the whole GROUPS block as one part', () => {
        const stored = { ...Store.current(), sections: ['groups', 'pinned', 'layouts', 'companies', 'rogue', 'terminals', 'browsers', 'review', 'pack'] };
        const keys = buildListPlan(stubs(), input([A, B, C, T], { arrangement: stored }))!.parts.map((p) => p.key);
        expect(keys[0]).toBe('groups');
        expect(keys.indexOf('pinned')).toBeGreaterThan(0);
    });

    it('`groups` is a fold key that keeps no band order of its own', () => {
        expect(isFoldKey('groups')).toBe(true);
        expect(isBandOrderKey('groups')).toBe(false);
        expect(isBandOrderKey('g:x')).toBe(true);
    });
});

describe('moving a group and moving the GROUPS section', () => {
    let w: LegacyWindow;
    let listEl: HTMLElement;
    const reorder = vi.fn(async (order: string[]) => ({
        status: 'ok', groups: order.map((uuid, position) => ({ ...GROUPS.find((g) => g.group_uuid === uuid)!, position })),
    }));

    function paint(): void {
        const rows = [A, B, C, T].map((r) => ({
            ...r, label: r.name, created_by_cloude: true, status: 'idle', unread: false, session_id: `ses_${r.name}`,
            session_uuid: `su-${r.name}`, kind: r.kind ?? 'agent', agent_family: r.agent_family ?? 'claude',
        }));
        const ctrl: Record<string, unknown> = { _rows: rows, _listing: { ok: true }, _lastSig: null, _dragging: false, _missing: [], listEl };
        ctrl.repaint = () => paintDrawer(ctrl);
        w.SessionSidebar = ctrl;
        unmountPanel(listEl.id);
        paintDrawer(ctrl);
    }

    function chord(key: string, arrow: 'ArrowUp' | 'ArrowDown'): void {
        const button = listEl.querySelector(`[data-group-toggle="${key}"]`) as HTMLElement;
        button.dispatchEvent(new KeyboardEvent('keydown', { key: arrow, altKey: true, bubbles: true, cancelable: true }));
    }

    beforeAll(() => {
        listEl = document.createElement('div');
        listEl.id = 'session-sidebar-list';
        listEl.className = 'session-sidebar-list';
        const live = document.createElement('div');
        live.id = 'session-sidebar-live';
        document.body.append(listEl, live);
        w = loadLegacyDrawer();
    });

    beforeEach(() => {
        reorder.mockClear();
        w.CloudeWeb = { layouts: { list: () => [], get: () => null, isUnavailable: () => false }, sidebarShell };
        w.API = { reorderSessionGroups: reorder };
        w.SessionSidebarStore.save([], [], [], {}, {});
        w.SessionSidebarGroupStore.apply({ status: 'ok', groups: GROUPS });
    });

    it('draws the groups inside the GROUPS wrapper, which alone is the section', () => {
        paint();
        const block = listEl.querySelector(':scope > [data-section="groups"]')!;
        expect(block).toBeTruthy();
        const bands = Array.from(block.querySelectorAll(':scope > .session-sidebar-group__body > .session-sidebar-group'));
        expect(bands.map((b) => b.getAttribute('data-group'))).toEqual(['g:x', 'g:y']);
        expect(bands.every((b) => !b.hasAttribute('data-section'))).toBe(true);
    });

    it('Alt+ArrowUp on the second group sends the whole new group order, and the first group is at the top edge', async () => {
        paint();
        chord('g:y', 'ArrowUp');
        await vi.waitFor(() => expect(reorder).toHaveBeenCalledTimes(1));
        expect(reorder).toHaveBeenCalledWith(['y', 'x', 'z']);
        paint();
        chord('g:y', 'ArrowUp');
        expect(document.getElementById('session-sidebar-live')!.textContent).toMatch(/top of the list/);
        expect(reorder).toHaveBeenCalledTimes(1);
    });

    it('Alt+ArrowDown on the GROUPS heading writes the section order and moves the whole block', () => {
        paint();
        chord('groups', 'ArrowDown');
        const stored = Store.current().sections as string[];
        expect(stored.indexOf('groups'), 'GROUPS moved below COMPANIES as one block').toBeGreaterThan(stored.indexOf('companies'));
        expect(reorder).not.toHaveBeenCalled();
    });
});

describe('the Shift+click cascade on GROUPS', () => {
    it('names every hand-made group, folded or not, as the keys under the heading', async () => {
        const { cascadeKeysFor } = await import('./cascade-keys');
        const world = { companyIds: [], companyParent: () => null, projects: [], layoutKeys: [], groupKeys: ['g:x', 'g:y', 'g:z'] };
        expect(cascadeKeysFor('groups', world)).toEqual({ tree: ['g:x', 'g:y', 'g:z'], inverted: [] });
        expect(cascadeKeysFor('groups', { ...world, groupKeys: undefined })).toEqual({ tree: [], inverted: [] });
    });
});
