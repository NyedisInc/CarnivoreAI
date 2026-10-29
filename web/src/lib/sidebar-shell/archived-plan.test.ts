/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { archivedRows } from '../drawer/archived-rows';
import { buildListPlan, type PaintInput } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [], companyOf: () => null }),
    watchCompanies: () => {},
}));
vi.mock('./leaders-source.svelte', async () => {
    const real = await import('./leaders');
    return { leaderIndex: () => real.indexLeaders([]), watchLeaders: () => {}, leaderRoster: () => [], projectNameOf: () => null };
});

function stubs(): LegacyDrawer {
    return {
        projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null },
    };
}
const input = (rows: SidebarRow[], query = ''): PaintInput => ({ rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: { query } });

function listed(): SidebarRow[] {
    return [
        { name: 'carnivore_live', status: 'idle', session_row_id: 1, project_id: 5, project_name: 'moved' },
        { name: 'carnivore_nap', status: 'asleep', asleep: true, session_uuid: 'u-nap', project_id: 5, project_name: 'moved' },
    ];
}
const archived = [
    { archived_at: '2026-10-01', session_uuid: 'u-old', tmux_name: null, title: 'zebra history', project_id: 5, project_name: 'moved' },
];

function loaded(shown: boolean): SidebarRow[] {
    const rows = listed();
    return [...rows, ...archivedRows(archived, shown, new Set(rows.map((r) => r.name)))] as SidebarRow[];
}

function projectKeys(rows: SidebarRow[], query = ''): string[] {
    const plan = buildListPlan(stubs(), input(rows, query))!;
    const json = JSON.stringify(plan.parts);
    return ['carnivore_live', 'carnivore_nap', 'archived:u-old'].filter((k) => json.includes(`"key":"${k}"`));
}

beforeEach(() => {
    (globalThis as { SessionLabel?: unknown }).SessionLabel = { resolve: (r: { label?: string | null }) => r.label ?? null };
    localStorage.clear();
    Store.load();
    setQuery('');
});

describe('show archived in the drawer plan', () => {
    it('off: the plan is byte-identical to a drawer with no archived sessions at all', () => {
        const before = JSON.stringify(buildListPlan(stubs(), input(listed())));
        const off = JSON.stringify(buildListPlan(stubs(), input(loaded(false))));
        expect(off).toBe(before);
        expect(off).not.toContain('archived');
        expect(off).not.toContain('zebra');
    });

    it('on: the archived session sits under its project after the others, marked archived', () => {
        const plan = buildListPlan(stubs(), input(loaded(true)))!;
        const sections = plan.parts.flatMap((p) => (p.type === 'company' ? p.sections : p.type === 'section' ? [p] : []));
        const section = sections.find((p) => p.rows.some((r) => r.key === 'archived:u-old'));
        if (!section || section.type !== 'section') throw new Error('archived row not drawn');
        expect(section.rows.map((r) => r.key)).toEqual(['carnivore_live', 'carnivore_nap', 'archived:u-old']);
        const row = section.rows[2] as { attrs: Record<string, string>; archived?: { svg: string; attrs: Record<string, string> } };
        expect(row.attrs['data-archived']).toBe('1');
        expect(row.attrs['data-asleep']).toBeUndefined();
        expect((row as unknown as { led: unknown }).led).toBeNull();
        expect(row.archived?.svg).toContain('<svg');
        expect(row.archived?.attrs['aria-label']).toBeTruthy();
        expect(row.archived?.attrs.title).toBe(row.archived?.attrs['aria-label']);
        expect('archived' in section.rows[0]!).toBe(false);
    });

    it('the search obeys the toggle: off never matches an archived session, on matches it like any row', () => {
        setQuery('zebra');
        expect(projectKeys(loaded(false), 'zebra')).toEqual([]);
        expect(projectKeys(loaded(true), 'zebra')).toEqual(['archived:u-old']);
    });
});
