/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import * as GroupStore from '../drawer/group-store';
import * as EmptySections from '../drawer/empty-sections.svelte';
import { EMPTY_CONTEXT, ruleOf } from '../drawer/group-rule';
import { countMatchingInContainer, scopeRowsForContainer } from '../drawer/nested-groups';
import { setQuery } from '../drawer/search';
import * as Store from '../drawer/store';
import { cascadeKeysFor } from './cascade-keys';
import { groupContainerChoices, groupContainerOptions } from './group-containers';
import NewGroupModal, { type NewGroupAnswer } from './NewGroupModal.svelte';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import { buildListPlan, type CompanyPlan, type GroupsPlan, type PaintInput, type SectionPlan } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';

const source = vi.hoisted(() => ({
    companies: [
        { id: 1, name: 'nyedis' },
        { id: 2, name: 'nyedis-sub' },
        { id: 3, name: 'other-co' },
    ] as Array<{ id: number; name: string }>,
    companyOf: { '10': 1, '11': 2, '20': 3 } as Record<string, number>,
    parentOf: { 2: 1 } as Record<number, number>,
}));

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({
        companies: source.companies,
        companyOf: (id: string) => source.companyOf[String(id)] ?? null,
        parentOf: (id: number) => source.parentOf[id] ?? null,
    }),
    watchCompanies: () => {},
}));
vi.mock('./pack-source.svelte', () => ({ packSource: () => [], watchPack: () => {} }));

const stubs = (): LegacyDrawer => ({
    projectHeader: {
        ledHtml: () => '',
        iconHtml: (n) => (n ? `<i data-glyph="${n}"></i>` : ''),
        iconForBand: () => null,
    },
});

const mkRow = (name: string, extra: Record<string, unknown> = {}): SidebarRow => ({
    name, label: name, kind: 'agent', agent_family: 'claude', status: 'idle', unread: false,
    is_pinned: false, created_by_cloude: true, session_id: `ses_${name}`, session_uuid: `su-${name}`,
    project_id: 10, project_name: 'carnivore', ...extra,
});

const ROWS: SidebarRow[] = [
    mkRow('cv-alpha', { is_pinned: true, project_id: 10, project_name: 'carnivore', status: 'working' }),
    mkRow('cv-sleep', { is_pinned: true, project_id: 10, project_name: 'carnivore', asleep: true }),
    mkRow('cv-wait', { project_id: 11, project_name: 'subproj', status: 'question' }),
    mkRow('arg-live', { project_id: 10, project_name: 'carnivore', status: 'working' }),
    mkRow('cv-other', { project_id: 20, project_name: 'foreign', status: 'working' }),
];

function paintPlan(collapsed: string[] = []): ReturnType<typeof buildListPlan> {
    GroupStore.setRuleContext(EMPTY_CONTEXT);
    GroupStore.setIdentities(ROWS as Array<{ name: string; session_uuid?: string | null }>);
    const input: PaintInput = {
        rows: ROWS, density: 'compact', listing: { ok: true }, missing: [],
        arrangement: { ...Store.current(), collapsed }, opts: {},
    };
    return buildListPlan(stubs(), input);
}

beforeAll(() => { loadLegacyDrawer(); });

beforeEach(() => {
    resetDrawer();
    EmptySections.setEmptySectionsHidden(true);
    Store.load();
    setQuery('');
    GroupStore.setRuleContext(EMPTY_CONTEXT);
});

describe('nested groups & container-scoped dynamic rules (#3369)', () => {
    it('dynamic group inside PINNED shows only matching pinned sessions', () => {
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-pin-active', name: 'active', position: 0, parent_key: 'pinned', rule: { flags: ['running'], prefix: '', suffix: '' }, members: [] },
            ],
        });
        const plan = paintPlan()!;
        expect(plan.parts.find((p) => p.type === 'groups')).toBeUndefined();
        const pinned = plan.parts.find((p): p is SectionPlan => p.type === 'section' && p.key === 'pinned')!;
        expect(pinned.groups?.map((g) => g.key)).toEqual(['g:g-pin-active']);
        const nested = pinned.groups![0]!;
        expect(nested.nested).toBe(true);
        expect(nested.rows.map((r) => r.key)).toEqual(['cv-alpha']);
        expect(pinned.rows.map((r) => r.key)).toEqual(['cv-sleep']);
        const nyedis = plan.parts.find((p): p is CompanyPlan => p.type === 'company' && p.key === 'c:1')!;
        expect(nyedis.sections.find((s) => s.key === 'p:10')!.rows.map((r) => r.key)).toContain('cv-alpha');
        expect(countMatchingInContainer(ruleOf({ flags: ['running'], prefix: '', suffix: '' })!, 'g-pin-active')).toBe(1);
    });

    it('dynamic group inside a company scopes to that company (plus child companies) and composes into nested subgroups all the way down', () => {
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-co-cv', name: 'cv', position: 0, parent_key: 'c:1', rule: { flags: [], prefix: 'cv', suffix: '' }, members: [] },
                { group_uuid: 'g-co-cv-run', name: 'live', position: 1, parent_key: 'g:g-co-cv', rule: { flags: ['running'], prefix: '', suffix: '' }, members: [] },
                { group_uuid: 'g-co-cv-wait', name: 'waiting', position: 2, parent_key: 'g:g-co-cv-run', rule: { flags: ['waiting'], prefix: '', suffix: '' }, members: [] },
            ],
        });
        const plan = paintPlan()!;
        const nyedis = plan.parts.find((p): p is CompanyPlan => p.type === 'company' && p.key === 'c:1')!;
        expect(nyedis.groups?.map((g) => g.key)).toEqual(['g:g-co-cv']);

        const gCv = nyedis.groups![0]!;
        expect(gCv.count).toBe(3);
        expect(gCv.rows.map((r) => r.key)).toEqual(['cv-sleep']);

        expect(gCv.groups?.map((g) => g.key)).toEqual(['g:g-co-cv-run']);
        const gRun = gCv.groups![0]!;
        expect(gRun.nested).toBe(true);
        expect(gRun.count).toBe(2);
        expect(gRun.rows.map((r) => r.key)).toEqual(['cv-alpha']);

        expect(gRun.groups?.map((g) => g.key)).toEqual(['g:g-co-cv-wait']);
        expect(gRun.groups![0]!.rows.map((r) => r.key)).toEqual(['cv-wait']);

        expect(nyedis.sections.find((s) => s.key === 'p:10')!.rows.map((r) => r.key)).toEqual(['arg-live']);
        expect(nyedis.children![0]!.sections.find((s) => s.key === 'p:11')!.rows.map((r) => r.key)).toEqual([]);
        const pinned = plan.parts.find((p): p is SectionPlan => p.type === 'section' && p.key === 'pinned')!;
        expect(pinned.rows.map((r) => r.key).sort()).toEqual(['cv-alpha', 'cv-sleep']);

        const coSrc = {
            companies: source.companies,
            companyOf: (id: string) => source.companyOf[String(id)] ?? null,
            parentOf: (id: number) => source.parentOf[id] ?? null,
        };
        expect(countMatchingInContainer(ruleOf({ flags: [], prefix: 'cv', suffix: '' })!, 'g-co-cv', coSrc)).toBe(3);
        expect(countMatchingInContainer(ruleOf({ flags: ['running'], prefix: '', suffix: '' })!, 'g-co-cv-run', coSrc)).toBe(2);
        expect(countMatchingInContainer(ruleOf({ flags: ['waiting'], prefix: '', suffix: '' })!, 'g-co-cv-wait', coSrc)).toBe(1);
    });

    it('dynamic group inside a project scopes only to that project and hides when the project folds', () => {
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-proj-cv', name: 'cv', position: 0, parent_key: 'p:10', rule: { flags: ['running'], prefix: 'cv', suffix: '' }, members: [] },
            ],
        });
        const plan = paintPlan()!;
        const nyedis = plan.parts.find((p): p is CompanyPlan => p.type === 'company' && p.key === 'c:1')!;
        const proj10 = nyedis.sections.find((s) => s.key === 'p:10')!;
        expect(proj10.groups?.map((g) => g.key)).toEqual(['g:g-proj-cv']);
        expect(proj10.groups![0]!.rows.map((r) => r.key)).toEqual(['cv-alpha']);
        expect(proj10.rows.map((r) => r.key).sort()).toEqual(['arg-live', 'cv-sleep']);

        const folded = paintPlan(['p:10'])!;
        const foldedNyedis = folded.parts.find((p): p is CompanyPlan => p.type === 'company' && p.key === 'c:1')!;
        expect(foldedNyedis.sections.find((s) => s.key === 'p:10')!.groups).toBeUndefined();
    });

    it('renders nested groups into the real DOM inside their container and uses the agent-group glyph for GROUPS', () => {
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-top', name: 'top', position: 0, parent_key: null, members: ['arg-live'] },
                { group_uuid: 'g-pin', name: 'live', position: 1, parent_key: 'pinned', rule: { flags: ['running'], prefix: '', suffix: '' }, members: [] },
            ],
        });
        const plan = paintPlan()!;
        const groups = plan.parts.find((p): p is GroupsPlan => p.type === 'groups')!;
        expect(groups.heading.iconHtml).toContain('data-glyph="agent-group"');
        expect(groups.heading.iconHtml).not.toContain('users');
        expect(groups.sections[0]!.heading.iconHtml).toContain('data-glyph="agent-group"');

        Store.save(['cv-alpha', 'cv-sleep'], ROWS.map((r) => r.name), []);
        drawList(ROWS as unknown as Record<string, unknown>[]);
        const list = document.getElementById('session-sidebar-list')!;
        const pinnedEl = list.querySelector('[data-group="pinned"]')!;
        const nestedEl = pinnedEl.querySelector(':scope > .session-sidebar-group__body > [data-group="g:g-pin"]');
        expect(nestedEl, 'nested group renders inside PINNED body').toBeTruthy();
        expect(nestedEl!.classList.contains('session-sidebar-group--nested')).toBe(true);
        expect(nestedEl!.querySelector('.session-sidebar-group__icon svg'), 'nested group wears default agent-group icon').toBeTruthy();
    });

    it('cascade fold collects nested groups under PINNED, companies, projects, and parent groups', () => {
        const parents: Record<string, string | null> = {
            'g:top': null,
            'g:pin1': 'pinned',
            'g:co1': 'c:1',
            'g:co1-sub': 'g:co1',
            'g:p10': 'p:10',
        };
        const world = {
            companyIds: [1],
            companyParent: () => null,
            projects: [{ id: '10', companyId: 1, parentId: null }],
            layoutKeys: [],
            groupKeys: Object.keys(parents),
            groupParent: (k: string) => parents[k] ?? null,
        };
        expect(cascadeKeysFor('groups', world).tree).toEqual(['g:top']);
        expect(cascadeKeysFor('pinned', world).tree).toEqual(['g:pin1']);
        expect(cascadeKeysFor('c:1', world).tree.sort()).toEqual(['g:co1', 'g:co1-sub', 'g:p10', 'p:10']);
        expect(cascadeKeysFor('p:10', world).tree).toEqual(['g:p10']);
        expect(cascadeKeysFor('g:co1', world).tree).toEqual(['g:co1-sub']);
    });

    it('hosts nested groups inside LAYOUTS, keeps empty nested groups visible with hideEmpty on, and guards cycles in container options (#3373)', () => {
        EmptySections.setEmptySectionsHidden(true);
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-lay', name: 'my layouts', position: 0, parent_key: 'layouts', members: [] },
                { group_uuid: 'g-empty-co', name: 'empty co group', position: 1, parent_key: 'c:1', members: [] },
                { group_uuid: 'g-child', name: 'child', position: 2, parent_key: 'g:g-empty-co', members: [] },
            ],
        });
        const plan = paintPlan()!;
        const layouts = plan.parts.find((p): p is SectionPlan => p.type === 'section' && p.key === 'layouts');
        expect(layouts?.groups?.map((g) => g.key)).toEqual(['g:g-lay']);
        const nyedis = plan.parts.find((p): p is CompanyPlan => p.type === 'company' && p.key === 'c:1')!;
        expect(nyedis.groups?.map((g) => g.key)).toEqual(['g:g-empty-co']);
        expect(nyedis.groups![0]!.groups?.map((g) => g.key)).toEqual(['g:g-child']);

        const opts = groupContainerOptions('g-empty-co');
        const keys = opts.map((o) => o.key);
        expect(keys).toContain(null);
        expect(keys).toContain('pinned');
        expect(keys).toContain('layouts');
        expect(keys).toContain('g:g-lay');
        expect(keys).not.toContain('g:g-empty-co');
        expect(keys).not.toContain('g:g-child');
    });

    it('NewGroupModal lets the user pick any container (company, pinned, layouts, top-level) and submits both (#3373)', () => {
        const host = document.createElement('div');
        document.body.appendChild(host);
        let settled: NewGroupAnswer | null | undefined;
        const inst = mount(NewGroupModal, {
            target: host,
            props: {
                initialParent: 'pinned',
                choices: groupContainerChoices(),
                close: (v) => { settled = v; },
            },
        });
        flushSync();
        const nameInput = host.querySelector('[data-new-group-name]') as HTMLInputElement;
        const locSelect = host.querySelector('[data-new-group-location]') as HTMLSelectElement;
        expect(nameInput).toBeTruthy();
        expect(locSelect.value).toBe('pinned');
        nameInput.value = 'active cv';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        locSelect.value = 'layouts';
        locSelect.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();
        (host.querySelector('[data-new-group-confirm]') as HTMLButtonElement).click();
        expect(settled).toEqual({ name: 'active cv', parentKey: 'layouts' });
        unmount(inst);
        host.remove();
    });

    it('nests groups inside an individual saved Layout (layout:<uuid>) with dynamic rules scoped to that Layout (#3383)', () => {
        GroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g-l1-run', name: 'live in layout', position: 0, parent_key: 'layout:L1', rule: { flags: ['running'], prefix: '', suffix: '' }, members: [] },
            ],
        });
        const layoutRow = {
            name: 'layout:L1',
            label: 'Dev Layout',
            kind: 'layout',
            layout_uuid: 'L1',
            _members: [ROWS[0]!, ROWS[1]!],
        };
        const scoped = scopeRowsForContainer('layout:L1', [...ROWS, layoutRow as unknown as SidebarRow]);
        expect(scoped.map((r) => r.name)).toEqual(['cv-alpha', 'cv-sleep']);
        GroupStore.setIdentities([...ROWS, layoutRow as unknown as SidebarRow] as Array<{ name: string; session_uuid?: string | null }>);
        expect(countMatchingInContainer(ruleOf({ flags: ['running'], prefix: '', suffix: '' })!, 'g-l1-run')).toBe(1);

        const win = globalThis as unknown as { CloudeWeb?: Record<string, unknown> };
        const prevWeb = win.CloudeWeb;
        win.CloudeWeb = {
            ...(prevWeb ?? {}),
            layouts: { list: () => [{ layout_uuid: 'L1', name: 'Dev Layout', position: 0, members: [{ session_uuid: 'su-cv-alpha' }, { session_uuid: 'su-cv-sleep' }] }], get: () => ({ layout_uuid: 'L1', name: 'Dev Layout', position: 0, members: [{ session_uuid: 'su-cv-alpha' }, { session_uuid: 'su-cv-sleep' }] }) },
        };
        try {
            expect(groupContainerOptions().map((o) => o.key)).toContain('layout:L1');

            Store.save([], ROWS.map((r) => r.name), ['layout:L1']);
            drawList([...ROWS, layoutRow] as unknown as Record<string, unknown>[]);
            const list = document.getElementById('session-sidebar-list')!;
            const membersEl = list.querySelector('[data-layout-members="L1"]')!;
            const nestedEl = membersEl.querySelector(':scope > [data-group="g:g-l1-run"]');
            expect(nestedEl, 'nested group renders inside expanded Layout body').toBeTruthy();
            const rowNames = Array.from(nestedEl!.querySelectorAll('.session-sidebar-row')).map((el) => el.getAttribute('data-name'));
            expect(rowNames).toEqual(['cv-alpha']);
            const directLayoutRows = Array.from(membersEl.querySelectorAll(':scope > .session-sidebar-row')).map((el) => el.getAttribute('data-name'));
            expect(directLayoutRows).toEqual(['cv-sleep']);

            Store.save([], ROWS.map((r) => r.name), ['layout:L1', 'g:g-l1-run']);
            drawList([...ROWS, layoutRow] as unknown as Record<string, unknown>[]);
            const directAfterFold = Array.from(list.querySelectorAll('[data-layout-members="L1"] > .session-sidebar-row')).map((el) => el.getAttribute('data-name'));
            expect(directAfterFold).toEqual(['cv-sleep']);

            GroupStore.apply({
                status: 'ok',
                groups: [{ group_uuid: 'g-top-only', name: 'top independent', position: 0, parent_key: null, members: ['cv-alpha'] }],
            });
            Store.save(['cv-alpha'], ROWS.map((r) => r.name), ['layout:L1']);
            drawList([...ROWS, layoutRow] as unknown as Record<string, unknown>[]);
            const directWithTopGroup = Array.from(list.querySelectorAll('[data-layout-members="L1"] > .session-sidebar-row')).map((el) => el.getAttribute('data-name'));
            expect(directWithTopGroup).toEqual(['cv-alpha', 'cv-sleep']);
            const pinnedDirect = Array.from(list.querySelectorAll('[data-group="pinned"] > .session-sidebar-group__body > .session-sidebar-row')).map((el) => el.getAttribute('data-name'));
            expect(pinnedDirect).toContain('cv-alpha');
        } finally {
            win.CloudeWeb = prevWeb;
        }
    });
});
