/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { archivedRows } from '../drawer/archived-rows';
import * as Archived from '../drawer/archived-visibility';
import { setDrawerEnv } from '../drawer/env';
import { buildListPlan, type CompanyPlan, type PaintInput } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';

const COMPANIES = vi.hoisted(() => [{ id: 1, name: 'acme', project_count: 1 }, { id: 9, name: 'Scratch', project_count: 1 }]);

vi.mock('../companies', () => ({ companyList: () => COMPANIES, companies: { list: COMPANIES } }));
vi.mock('../../opscenter/api/projects.svelte', () => ({
    projects: { data: [{ id: 3, name: 'live', path: '/x/live', archived_at: null, company_id: 1, parent_project_id: null }] },
}));
vi.mock('./interaction-globals', () => ({ repaintDrawerRows: () => {} }));
vi.mock('./leaders-source.svelte', async () => {
    const real = await import('./leaders');
    return { leaderIndex: () => real.indexLeaders([]), watchLeaders: () => {}, leaderRoster: () => [], projectNameOf: () => null };
});

const ALL_PROJECTS = [
    { id: 3, name: 'live', archived_at: null, company_id: 1, parent_project_id: null },
    { id: 42, name: 'old-scratch', archived_at: '2026-10-09T01:00:00', company_id: 9, parent_project_id: null },
];
const ARCHIVED_SESSIONS = [
    { archived_at: '2026-10-09T01:00:00', session_uuid: 'u-old', tmux_name: null, title: 'old work', project_id: 42, project_name: 'old-scratch' },
];

const getProjects = vi.fn(async (includeArchived?: boolean) => (includeArchived ? ALL_PROJECTS : ALL_PROJECTS.filter((p) => !p.archived_at)));
const listArchivedSessionRecords = vi.fn(async () => ARCHIVED_SESSIONS);

function stubs(): LegacyDrawer {
    return {
        groups: {},
        projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null },
    };
}
const input = (rows: SidebarRow[]): PaintInput => ({ rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: { query: '' } });

function loaded(): SidebarRow[] {
    const live: SidebarRow[] = [{ name: 'carnivore_live', status: 'idle', session_row_id: 1, project_id: 3, project_name: 'live' }];
    return [...live, ...archivedRows(Archived.archivedRecords(), Archived.archivedShown(), new Set(live.map((r) => r.name)))] as SidebarRow[];
}

function companies(rows: SidebarRow[]): CompanyPlan[] {
    const plan = buildListPlan(stubs(), input(rows))!;
    const out: CompanyPlan[] = [];
    const walk = (c: CompanyPlan): void => { out.push(c); (c.children ?? []).forEach(walk); };
    plan.parts.forEach((p) => { if (p.type === 'company') walk(p); });
    return out;
}

beforeEach(() => {
    (globalThis as { SessionLabel?: unknown }).SessionLabel = { resolve: (r: { label?: string | null }) => r.label ?? null };
    setDrawerEnv({ API: { getProjects, listArchivedSessionRecords }, localStorage: globalThis.localStorage });
    localStorage.clear();
    Store.load();
    setQuery('');
    getProjects.mockClear();
});
afterEach(() => { Archived.setArchivedShown(false); setDrawerEnv(null); });

describe('archived projects under their company', () => {
    it('on: an archived-only company holds its archived project and that project\'s archived session', async () => {
        Archived.setArchivedShown(true);
        await Archived.refresh();
        const all = companies(loaded());
        const scratch = all.find((c) => c.key === 'c:9')!;
        expect(scratch.sections.map((s) => s.key)).toEqual(['p:42']);
        expect(scratch.sections[0]!.rows.map((r) => r.key)).toEqual(['archived:u-old']);
        expect(scratch.empty).toBe(false);
        expect(scratch.sections[0]!.heading.inactive?.attrs['aria-label']).toBe('inactive project');
        expect(all.find((c) => c.key === 'c:1')!.sections[0]!.heading.inactive).toBeUndefined();
        expect(all.find((c) => c.key === 'c:orphaned')).toBeUndefined();
    });

    it('off: no archived project is read and the drawer is what it was', async () => {
        await Archived.refresh();
        expect(getProjects).not.toHaveBeenCalled();
        const all = companies(loaded());
        expect(all.find((c) => c.key === 'c:9')!.sections).toEqual([]);
        expect(all.find((c) => c.key === 'c:1')!.sections.map((s) => s.key)).toEqual(['p:3']);
    });
});
