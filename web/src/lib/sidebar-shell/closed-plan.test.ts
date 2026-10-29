/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { addClosedRows } from '../drawer/closed';
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
        groups: {},
        projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null },
    };
}
const input = (rows: SidebarRow[], density = 'compact'): PaintInput => ({ rows, density, listing: { ok: true }, missing: [], arrangement: null, opts: { query: '' } });

const RECORDS = [
    { closed: true, session_uuid: 'u-closed', tmux_name: 'carnivore_closed', title: 'shut', project_id: 5, project_name: 'moved', agent_family: 'claude' },
    { archived_at: '2026-10-01', session_uuid: 'u-old', tmux_name: null, title: 'history', project_id: 5, project_name: 'moved', agent_family: 'claude' },
];

function loaded(shown: boolean): SidebarRow[] {
    const rows: Array<Record<string, unknown>> = [
        { name: 'carnivore_live', status: 'idle', agent_family: 'claude', session_row_id: 1, session_id: 'ses_1', project_id: 5, project_name: 'moved' },
        { name: 'carnivore_nap', status: 'asleep', asleep: true, agent_family: 'claude', session_uuid: 'u-nap', project_id: 5, project_name: 'moved' },
    ];
    addClosedRows(rows, RECORDS);
    rows.push(...archivedRows(RECORDS, shown, new Set(rows.map((r) => String(r.name)))));
    return rows as SidebarRow[];
}

interface DrawnRow { key: string; attrs: Record<string, string | undefined>; led: { status: string } | null; closed?: { text: string; attrs: Record<string, string> }; archived?: unknown }

function drawn(rows: SidebarRow[], density = 'compact'): Record<string, DrawnRow> {
    const plan = buildListPlan(stubs(), input(rows, density))!;
    const out: Record<string, DrawnRow> = {};
    const walk = (node: unknown): void => {
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (!node || typeof node !== 'object') return;
        const o = node as Record<string, unknown>;
        if (o.type === 'session' && typeof o.key === 'string') out[o.key] = o as unknown as DrawnRow;
        Object.values(o).forEach(walk);
    };
    walk(plan.parts);
    return out;
}

beforeEach(() => {
    (globalThis as { SessionLabel?: unknown }).SessionLabel = { resolve: (r: { label?: string | null }) => r.label ?? null };
    localStorage.clear();
    Store.load();
});

describe('closed, asleep and archived are three looks', () => {
    it('show archived OFF: live, asleep and closed rows are listed, the archived one is not', () => {
        expect(Object.keys(drawn(loaded(false))).sort()).toEqual(['carnivore_closed', 'carnivore_live', 'carnivore_nap']);
    });

    it('show archived ON: the archived row joins; the others stay', () => {
        expect(Object.keys(drawn(loaded(true))).sort()).toEqual(['archived:u-old', 'carnivore_closed', 'carnivore_live', 'carnivore_nap']);
    });

    for (const shown of [false, true]) {
        it(`closed row looks the same with the toggle ${shown ? 'on' : 'off'}: its chip, no light, never asleep or archived`, () => {
            const row = drawn(loaded(shown))['carnivore_closed']!;
            expect(row.attrs['data-closed']).toBe('1');
            expect(row.attrs['data-asleep']).toBeUndefined();
            expect(row.attrs['data-archived']).toBeUndefined();
            expect(row.led).toBeNull();
            expect(row.closed?.text).toBe('closed');
            expect(row.closed?.attrs.class).toContain('session-sidebar-row-closed');
            expect(row.archived).toBeUndefined();
        });
    }

    it('asleep keeps its moon and wears no closed chip; archived keeps its box and wears no closed chip', () => {
        const rows = drawn(loaded(true));
        const nap = rows['carnivore_nap']!;
        expect(nap.led?.status).toBe('asleep');
        expect(nap.closed).toBeUndefined();
        expect(nap.attrs['data-closed']).toBeUndefined();
        const old = rows['archived:u-old']!;
        expect(old.attrs['data-archived']).toBe('1');
        expect(old.archived).toBeTruthy();
        expect(old.closed).toBeUndefined();
        expect(rows['carnivore_live']!.closed).toBeUndefined();
    });

    it('every density draws the chip and no light on the closed row', () => {
        for (const density of ['compact', 'cozy', 'detailed']) {
            const row = drawn(loaded(false), density)['carnivore_closed']!;
            expect(row.closed?.text).toBe('closed');
            expect(row.led).toBeNull();
        }
    });
});
