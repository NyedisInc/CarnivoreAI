import { expect, test } from 'vitest';
import { laneColor, planLanes } from './timeline-model';
import { session } from '../projects-shared/test-fixtures';
import type { PageRow, Signals } from './filters';

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
const sig: Signals = { live: () => ({ activity_status: 'question' }) as never, asleepUnread: () => false };
const mk = (label: string, project: { id: number; name: string } | null, key: string): PageRow => ({
    s: session({ session_uuid: label, label, state: 'running', row_id: 1 }),
    groupKey: key, projectRef: project as PageRow['projectRef'], project: project?.name ?? 'no project', company: null, computer: null, provider: 'claude',
});

test('needs-you lanes group by project a to z, sessions a to z, no project last', () => {
    const rows = [mk('zed', null, 'n'), mk('b2', { id: 2, name: 'beta' }, 'p2'), mk('A1', { id: 1, name: 'Alpha' }, 'p1'), mk('a0', { id: 1, name: 'Alpha' }, 'p1'), mk('b1', { id: 2, name: 'beta' }, 'p2')];
    const plan = planLanes(rows, sig, 60, NOW);
    expect(plan.needs.map((g) => g.project)).toEqual(['Alpha', 'beta', 'no project']);
    expect(plan.needs.map((g) => g.rows.map((r) => r.s.label))).toEqual([['a0', 'A1'], ['b1', 'b2'], ['zed']]);
});

test('a project with a color colors its lanes, one without keeps green', () => {
    const colorOf = (id: number | null): string | null => (id === 1 ? '#966356' : null);
    expect(laneColor({ id: 1, name: 'x' } as PageRow['projectRef'], colorOf)).toBe('#966356');
    expect(laneColor({ id: 2, name: 'y' } as PageRow['projectRef'], colorOf)).toBeUndefined();
    expect(laneColor(null, colorOf)).toBeUndefined();
});
