import { describe, expect, it } from 'vitest';
import { BIG, LONG_TAIL, MANY_ROWS, stressTable, stressValue } from './stress';
import { fixtureFor } from './index';

describe('stressValue', () => {
  it('stretches a display name, multiplies a count, and leaves a time, an id and an enum alone', () => {
    const out = stressValue({ name: 'api', status: 'working', count: 8, updated_at: 17, used_pct: 40, id: 'a' }) as Record<string, unknown>;
    expect(out).toEqual({ name: `api${LONG_TAIL}`, status: 'working', count: 8 * BIG, updated_at: 17, used_pct: 40, id: 'a' });
  });

  it('repeats a list of records up to MANY_ROWS with unique identities, and stretches a joined name the same way twice', () => {
    const rows = stressValue([{ id: 'a', project_name: 'web' }, { id: 'b', project_name: 'web' }]) as Array<Record<string, unknown>>;
    expect(rows).toHaveLength(MANY_ROWS);
    expect(new Set(rows.map((row) => row.id)).size).toBe(MANY_ROWS);
    expect(new Set(rows.map((row) => row.project_name))).toEqual(new Set([`web${LONG_TAIL}`]));
  });

  it('keeps a series (points with no identity) at its own length', () => {
    expect(stressValue([{ t: 1, v: 2 }, { t: 2, v: 3 }])).toHaveLength(2);
  });
});

describe('stressTable', () => {
  it('stresses a function answer on every call and is what fixtureFor answers for stress', () => {
    const table = stressTable({ 'GET /x': () => ({ total: 2 }) });
    expect((table['GET /x'] as () => unknown)()).toEqual({ total: 2 * BIG });
    const stressed = fixtureFor('core.running-sessions', 'stress')['GET /sessions/list'] as unknown[];
    const data = fixtureFor('core.running-sessions', 'data')['GET /sessions/list'] as unknown[];
    expect(data.length).toBeGreaterThan(0);
    expect(stressed.length).toBe(Math.max(MANY_ROWS, data.length));
  });
});
