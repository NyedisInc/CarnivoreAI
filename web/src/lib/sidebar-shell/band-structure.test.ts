/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import SidebarList from './SidebarList.svelte';
import { ShellView } from './shell.svelte';
import { canonicalDom, loadLegacyDrawer } from './legacy-fixture';
import type { BandPart, HeadingMenuPlan, HeadingPlan, ListPlan, SectionPlan } from './plan';
import type { RowPlan } from './row-plan';

loadLegacyDrawer();

function head(key: string, bandKind: HeadingPlan['bandKind'], menu: HeadingMenuPlan | null, extra: Partial<HeadingPlan> = {}): HeadingPlan {
    return {
        toggle: 'group', key, bandKind, expanded: true, bodyId: `session-sidebar-group-body-${key}`,
        title: `Collapse the ${key} group`, label: key,
        iconHtml: '<span class="i"></span>', ledHtml: '<span class="led"></span>', pickedIconHtml: '', rollupHtml: '',
        ...(menu ? { menu } : {}),
        ...extra,
    };
}

function layoutPlan(key: string): RowPlan {
    const parts = {
        attrs: { class: 'session-sidebar-row', 'data-name': key }, lightHtml: '', toggle: null, icon: null,
        name: { attrs: { class: 'session-sidebar-row-name' }, text: key, fxHtml: '' }, subtitle: '', pin: { name: key, pinned: false },
        menuContext: {},
    };
    return { type: 'layout', key, parts, pin: {}, menu: null, nameMatch: null, members: null } as unknown as RowPlan;
}

function row(key: string): RowPlan {
    return layoutPlan(key);
}

function section(key: string, h: HeadingPlan, rows: RowPlan[], extra: Partial<SectionPlan> = {}): SectionPlan {
    return {
        type: 'section', key, colourAttrs: {}, collapsed: false, count: rows.length, bodyId: h.bodyId, heading: h,
        rows, spawned: null, ...extra,
    };
}

function plan(): ListPlan {
    const child = section('p:2', head('p:2', 'project', { kind: 'project', id: 'p:2', label: 'rename, sleep or remove the child project' }), [row('c1')], { nested: true });
    const project = section('p:1', head('p:1', 'project', { kind: 'project', id: 'p:1', label: 'rename, sleep or remove the api project' }), [row('a1'), row('a2')], {
        colourAttrs: { 'data-colour': 'teal' },
        blockColor: 'rgb(1, 2, 3)',
        children: [child],
        spawned: { key: 'p:1:agents', collapsed: false, count: 1, heading: head('p:1:agents', 'reserved', null), rows: [row('s1')] },
    });
    const parts: BandPart[] = [
        { type: 'leader', key: 'leader', row: row('alpha') },
        section('pinned', head('pinned', 'reserved', null), [row('p1')]),
        { type: 'companies', key: 'companies', open: true, heading: head('companies', 'reserved', null) },
        {
            type: 'company', key: 'c:1', open: true, empty: false, leader: row('lead1'),
            heading: head('c:1', 'company', { kind: 'company', id: 'c:1', label: 'acme company menu' }, { tint: 'rgb(9, 9, 9)' }),
            sections: [project],
            children: [{
                type: 'company', key: 'c:3', open: true, empty: true, leader: null,
                heading: head('c:3', 'company', { kind: 'company', id: 'c:3', label: 'sub company menu' }), sections: [],
            }],
        },
        { type: 'company', key: 'c:orphaned', open: false, empty: false, leader: null, heading: head('c:orphaned', 'reserved', null, { expanded: false }), sections: [] },
        {
            type: 'groups', key: 'groups', open: true, heading: head('groups', 'reserved', null),
            sections: [section('g:u1', head('g:u1', 'group', { kind: 'group', id: 'u1', label: 'Rename, sleep, reorder or remove the work group' }), [row('g1')])],
        },
        section('terminals', head('terminals', 'reserved', null), [], { empty: 'no terminals' }),
        { type: 'pack', key: 'pack', open: true, density: 'compact', count: 0, rows: [], heading: head('pack', 'reserved', null) },
    ];
    return { leadHtml: '<div class="lead"></div>', parts, tailHtml: '<div class="tail"></div>' };
}

let handle: ReturnType<typeof mount> | null = null;
beforeEach(() => {
    document.body.innerHTML = '';
    (globalThis as Record<string, unknown>).ResizeObserver = class { observe(): void {} disconnect(): void {} };
});
afterEach(() => { if (handle) unmount(handle); handle = null; });

describe('drawer band wrappers and heading kebabs', () => {
    it('draw the recorded DOM for every band kind', async () => {
        const view = new ShellView();
        view.plan = plan();
        const target = document.body.appendChild(document.createElement('div'));
        handle = mount(SidebarList, { target, props: { view } });
        flushSync();
        await expect(canonicalDom(target)).toMatchFileSnapshot('./__goldens__/band-structure.html');
    });
});
