import { describe, expect, it } from 'vitest';
import { insertDefaultAnalytics, resetLayout } from './model';
import { META } from './meta';

const ids = [1, 2, 3, 4, 5].map((n) => `analytics:00000000-0000-4000-8000-00000000000${n}` as const);

describe('the default Home layout', () => {
  it('is the stat strip, the chart rows, running sessions with the ledger, then closed, skills and plugins, in that order', () => {
    const layout = insertDefaultAnalytics(resetLayout(META), ids);
    expect(layout.rows.map((row) => row.slots.map((slot) => slot.id.replace(/-0+(\d)$/, '#$1')))).toEqual([
      ['stat-running', 'stat-sessions', 'stat-projects', 'stat-ledger', 'stat-alive', 'stat-subagents'],
      ['analytics:00000000-0000-4000-8000#1', 'analytics:00000000-0000-4000-8000#2'],
      ['analytics:00000000-0000-4000-8000#3', 'analytics:00000000-0000-4000-8000#4', 'analytics:00000000-0000-4000-8000#5'],
      ['running-sessions', 'ledger'],
      ['closed-sessions', 'skills', 'plugins'],
      ['themes', 'activity-log'],
    ]);
    expect(layout.rows.map((row) => Math.round(row.size))).toEqual([69, 224, 252, 279, 198, 160]);
    expect(layout.rows[1]?.slots.map((slot) => Number(slot.fr.toFixed(4)))).toEqual([0.6667, 0.3333]);
    expect(layout.rows[2]?.slots.map((slot) => Number(slot.fr.toFixed(4)))).toEqual([0.3339, 0.3333, 0.3328]);
    expect(layout.rows[3]?.slots.map((slot) => Number(slot.fr.toFixed(4)))).toEqual([0.5321, 0.4679]);
    expect(layout.hidden).toContain('projects');
    expect(layout.collapsed).toEqual(['themes']);
  });

  it('leaves a layout that already holds charts to the old placement, with no row of it moved', () => {
    const saved = insertDefaultAnalytics(resetLayout(META), ids);
    const again = insertDefaultAnalytics(saved, ['analytics:00000000-0000-4000-8000-000000000009']);
    expect(again.rows.filter((row) => saved.rows.some((r) => r.id === row.id)).map((row) => row.slots)).toEqual(saved.rows.map((row) => row.slots));
  });
});
