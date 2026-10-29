/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Store from '../drawer/store';

const source = vi.hoisted(() => ({
    companies: [] as Array<{ id: number; name: string; parent_id?: number | null }>,
    companyOf: {} as Record<string, number>,
    parents: null as Record<number, number> | null,
    projectParents: null as Record<string, string> | null,
}));

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({
        companies: source.companies,
        companyOf: (id: string) => source.companyOf[String(id)] ?? null,
        ...(source.parents ? { parentOf: (id: number) => source.parents![id] ?? null } : {}),
        ...(source.projectParents ? { projectParentOf: (id: string) => source.projectParents![id] ?? null } : {}),
    }),
    watchCompanies: () => {},
}));

const row = (name: string, projectId: number, projectName: string): Record<string, unknown> => ({
    name, created_by_cloude: true, status: 'idle', unread: false, is_pinned: false, project_id: projectId, project_name: projectName,
});

const rows = [row('cloude_a', 1, 'amerifund'), row('cloude_b', 2, 'support'), row('cloude_c', 3, 'shelving'), row('cloude_d', 4, 'loose')];

function draw(collapsed: string[] = []): HTMLElement {
    Store.save([], rows.map((r) => r.name as string), collapsed);
    drawList(rows);
    return document.getElementById('session-sidebar-list')!;
}

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => {
    resetDrawer();
    source.companies = [{ id: 7, name: 'imc' }, { id: 8, name: 'amerifund co' }, { id: 9, name: 'ventures' }];
    source.companyOf = { 1: 8, 2: 8, 3: 9 };
    source.parents = null;
    source.projectParents = null;
});

describe('agents tab lineage tree', () => {
    it('draws byte-identical markup when nothing has a parent', () => {
        const before = draw().innerHTML;
        resetDrawer();
        source.parents = {};
        source.projectParents = {};
        const after = draw().innerHTML;
        expect(after).toBe(before);
        expect(after).not.toContain('session-sidebar-group--nested');
    });

    it('nests a child company inside its parent, each with its own fold', () => {
        source.parents = { 8: 7 };
        const list = draw();
        const imc = list.querySelector('.session-sidebar-company[data-company="c:7"]')!;
        const child = imc.querySelector(':scope > .session-sidebar-group__body > .session-sidebar-company[data-company="c:8"]');
        expect(child, 'amerifund co sits inside imc').toBeTruthy();
        expect(child!.querySelector('[data-group="p:1"]')).toBeTruthy();
        const top = Array.from(list.querySelectorAll('.session-sidebar-companies > .session-sidebar-group__body > .session-sidebar-company'))
            .map((el) => el.getAttribute('data-company'));
        expect(top).toEqual(['c:7', 'c:9', 'c:orphaned']);
        expect(imc.querySelector('.session-sidebar-company__empty')).toBeNull();

        const childFolded = draw(['c:8']);
        expect(childFolded.querySelector('[data-company="c:8"]')!.getAttribute('data-company-open')).toBe('0');
        expect(childFolded.querySelector('[data-group="p:1"]')).toBeNull();
        const parentFolded = draw(['c:7']);
        expect(parentFolded.querySelector('[data-company="c:8"]')).toBeNull();
    });

    it('nests a project inside its parent project of the same company, never across companies', () => {
        source.projectParents = { 2: '1', 3: '1' };
        const list = draw();
        const parent = list.querySelector('[data-group="p:1"]')!;
        const nested = parent.querySelector(':scope > .session-sidebar-group__body > .session-sidebar-group--nested[data-group="p:2"]');
        expect(nested, 'support sits inside amerifund').toBeTruthy();
        expect(nested!.querySelector('.session-sidebar-row[data-name="cloude_b"]')).toBeTruthy();
        const shelving = list.querySelector('[data-group="p:3"]')!;
        expect(shelving.classList.contains('session-sidebar-group--nested')).toBe(false);
        expect(shelving.closest('[data-company="c:9"]')).toBeTruthy();
        expect(draw(['p:1']).querySelector('[data-group="p:2"]')).toBeNull();
    });
});
