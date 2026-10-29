/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { buildListPlan, type PaintInput } from './plan';
import type { RowPlan } from './row-plan';
import { indexLeaders } from './leaders';
import { init as initLeaderToggle, setLeadersShown } from '../drawer/leader-visibility';
import type { LegacyDrawer, SidebarRow } from './legacy';

const roster = vi.hoisted(() => ({ agents: [] as unknown[] }));
vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [{ id: 7, name: 'acme' }, { id: 8, name: 'zeta' }], companyOf: (id: string) => (id === '1' || id === '3' ? 7 : null) }),
    watchCompanies: () => {},
}));
vi.mock('./leaders-source.svelte', async () => {
    const real = await import('./leaders');
    return {
        leaderIndex: () => real.indexLeaders(roster.agents as Parameters<typeof indexLeaders>[0]), watchLeaders: () => {},
        leaderRoster: () => roster.agents, projectNameOf: (id: number) => ({ 1: 'one', 2: 'hq', 3: 'example', 4: 'loose' } as Record<number, string>)[id] ?? null,
    };
});

function stubs(): LegacyDrawer {
    return {
        groups: {},
        projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null },
    };
}
const input = (rows: SidebarRow[], query = ''): PaintInput => ({ rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: { query } });

const alpha: SidebarRow = { name: 'cloude_alpha', session_row_id: 10, project_id: null };
const boss: SidebarRow = { name: 'cloude_boss', session_row_id: 11, project_id: 2, project_name: 'hq' };
const task: SidebarRow = { name: 'cloude_task', session_row_id: 20, project_id: 1, project_name: 'one' };
const lead: SidebarRow = { name: 'cloude_lead', session_row_id: 12, project_id: 1, project_name: 'one' };
const rows = [task, lead, boss, alpha];

beforeEach(() => {
    localStorage.clear();
    initLeaderToggle();
    Store.load();
    setQuery('');
    roster.agents = [
        { id: 1, rank: 'alpha', display_name: 'Alpha', session_row_id: 10 },
        { id: 2, rank: 'company', display_name: 'Acme HQ', session_row_id: 11, company_id: 7 },
        { id: 3, rank: 'project', display_name: 'One lead', session_row_id: 12 },
    ];
});

describe('leader placement in the plan', () => {
    it('Alpha first of all, the company agent first under its company, the project agent first in its project', () => {
        const plan = buildListPlan(stubs(), input(rows))!;
        expect(plan.parts[0]).toMatchObject({ type: 'leader', key: 'leader:alpha' });
        const company = plan.parts.find((p) => p.key === 'c:7');
        expect(company?.type).toBe('company');
        if (company?.type !== 'company') return;
        expect(company.leader?.key).toBe('cloude_boss');
        expect(company.sections[0]?.rows.map((r) => r.key)).toEqual(['cloude_lead', 'cloude_task']);
        const marks = [company.leader, ...company.sections[0]!.rows, (plan.parts[0] as { row: RowPlan | null }).row]
            .map((r) => (r && r.type === 'session' ? r.leader?.rank ?? null : null));
        expect(marks).toEqual(['company', 'project', null, 'alpha']);
        expect(company.empty).toBe(false);
        expect(JSON.stringify(plan.parts.filter((p) => p.type === 'section'))).not.toContain('cloude_alpha');
    });

    it('a query that matches nothing of a leader hides it, a drawer with no Swarm draws as before', () => {
        setQuery('task');
        const hidden = buildListPlan(stubs(), input(rows, 'task'))!;
        expect(hidden.parts.some((p) => p.type === 'leader')).toBe(false);
        setQuery('');
        roster.agents = [];
        const plain = buildListPlan(stubs(), input(rows))!;
        expect(plain.parts.some((p) => p.type === 'leader')).toBe(false);
        const orphan = plain.parts.find((p) => p.key === 'c:7');
        expect(orphan?.type === 'company' && orphan.leader).toBeNull();
    });

    it('a leader with no listing row is drawn from the roster: Alpha on top, company agent first under its heading, project agent first in its band', () => {
        roster.agents = [
            { id: 1, rank: 'alpha', display_name: 'Alpha', project_id: 71 },
            { id: 2, rank: 'company', display_name: 'Acme HQ', company_id: 7, project_id: 2 },
            { id: 3, rank: 'project', display_name: 'One lead', company_id: 7, project_id: 1 },
            { id: 4, rank: 'project', display_name: 'Example agent', company_id: 7, project_id: 3 },
            { id: 5, rank: 'project', display_name: 'Loose agent', project_id: 4 },
        ];
        const plan = buildListPlan(stubs(), input([task]))!;
        expect(plan.parts[0]).toMatchObject({ type: 'leader', key: 'leader:alpha' });
        const alphaRow = (plan.parts[0] as { row: { ghost?: { rank: string } | null; attrs: Record<string, string> } }).row;
        expect(alphaRow.ghost?.rank).toBe('alpha');
        expect(alphaRow.attrs['data-leader']).toBe('alpha');
        const company = plan.parts.find((p) => p.key === 'c:7');
        if (company?.type !== 'company') throw new Error('company missing');
        expect((company.leader as { ghost?: { agentId: number } }).ghost?.agentId).toBe(2);
        const bands = company.sections.map((s) => s.rows.map((r) => r.key));
        expect(bands).toContainEqual(['swarm-agent:3', 'cloude_task']);
        expect(bands).toContainEqual(['swarm-agent:4']);
        expect(JSON.stringify(plan.parts)).toContain('swarm-agent:5');
    });

    it('with no listing rows at all the leaders still draw (an install that never woke any)', () => {
        roster.agents = [{ id: 1, rank: 'alpha', display_name: 'Alpha', project_id: 71 }];
        const plan = buildListPlan(stubs(), input([]))!;
        expect(plan.parts[0]).toMatchObject({ type: 'leader', key: 'leader:alpha' });
    });
    it('the leaders toggle hides SysOp, company and project agents (listed and ghost) and keeps sessions, feature and task agents', () => {
        const feature: SidebarRow = { name: 'cloude_feature', session_row_id: 21, project_id: 1, project_name: 'one' };
        const worker: SidebarRow = { name: 'cloude_worker', session_row_id: 22, project_id: 1, project_name: 'one' };
        roster.agents = [
            ...roster.agents,
            { id: 4, rank: 'feature', display_name: 'A feature', session_row_id: 21 },
            { id: 5, rank: 'task', display_name: 'A task', session_row_id: 22 },
            { id: 6, rank: 'project', display_name: 'Ghost lead', project_id: 4 },
        ];
        const all = [task, lead, boss, alpha, feature, worker];
        const shown = JSON.stringify(buildListPlan(stubs(), input(all))!.parts);
        for (const key of ['cloude_alpha', 'cloude_boss', 'cloude_lead', 'swarm-agent:6']) expect(shown).toContain(key);
        setLeadersShown(false);
        const plan = buildListPlan(stubs(), input(all))!;
        const hidden = JSON.stringify(plan.parts);
        expect(plan.parts.some((p) => p.type === 'leader')).toBe(false);
        for (const key of ['cloude_alpha', 'cloude_boss', 'cloude_lead', 'swarm-agent:6']) expect(hidden).not.toContain(key);
        for (const key of ['cloude_task', 'cloude_feature', 'cloude_worker']) expect(hidden).toContain(key);
        setLeadersShown(true);
        expect(JSON.stringify(buildListPlan(stubs(), input(all))!.parts)).toContain('cloude_alpha');
    });
});
