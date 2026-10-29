import { describe, expect, test, vi } from 'vitest';
import { META } from '../../engine/meta';
import { addInstance, resetLayout, resizeColumns } from '../../engine/model';
import { validate } from '../../engine/persist';
import type { QueryBody } from './types';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn() }));

describe('independent analytics cells', () => {
  test('two UUID instances keep their identities and geometry through validation', () => {
    const first = 'c3f21b4b-4171-4249-8e85-6653ebc5aa96';
    const second = '94047a28-7d49-4075-8da7-a3abd732a134';
    let layout = resetLayout(META, 'home');
    layout = addInstance(layout, 'analytics', first, '').layout;
    layout = addInstance(layout, 'analytics', second, '').layout;
    const row = layout.rows.at(-1)!;
    layout = resizeColumns(layout, row.id, row.slots.length - 2, 20, 900, 100, 700);
    const saved = validate(JSON.parse(JSON.stringify(layout)), META, 'home');
    expect(saved.refusal).toBeNull();
    expect(saved.layout?.rows.flatMap((one) => one.slots.map((slot) => slot.id))).toContain(`analytics:${first}`);
    expect(saved.layout?.rows.flatMap((one) => one.slots.map((slot) => slot.id))).toContain(`analytics:${second}`);
    expect(saved.layout?.rows.at(-1)?.slots.at(-1)?.fr).toBeCloseTo(layout.rows.at(-1)!.slots.at(-1)!.fr);
  });

  test('changing one saved definition leaves the other untouched', async () => {
    const { analytics, changeChart } = await import('./state.svelte');
    const base = { revision: 1, enabled: true, series: [{ metric: 'total_tokens' }], filters: {},
      range: { mode: 'global' as const }, display: { type: 'line' as const } };
    analytics.charts = {
      one: { ...base, id: 'one', title: 'first' },
      two: { ...base, id: 'two', title: 'second' },
    };
    changeChart({ ...analytics.charts.one!, title: 'changed' });
    expect(analytics.charts.one!.title).toBe('changed');
    expect(analytics.charts.two!.title).toBe('second');
  });
});

describe('chart writes', () => {
  test('writes only schema fields from a server chart carrying timestamps', async () => {
    const { authFetch } = await import('../../api/auth.svelte');
    const { createChart, updateChart } = await import('./api');
    vi.mocked(authFetch).mockReset();
    vi.mocked(authFetch).mockResolvedValue({} as never);
    const config = {
      id: 'c3f21b4b-4171-4249-8e85-6653ebc5aa96', revision: 2, title: 'test', enabled: true,
      series: [{ metric: 'total_tokens', visible: true, filters: {}, transform: 'total' as const }], filters: {},
      range: { mode: 'global' as const }, display: { type: 'line' as const },
      created_at: '2026-09-01T00:00:00Z',
    };
    await createChart(config);
    await updateChart(config);
    const created = JSON.parse(String(vi.mocked(authFetch).mock.calls[0]?.[1]?.body));
    const patched = JSON.parse(String(vi.mocked(authFetch).mock.calls[1]?.[1]?.body));
    expect(created).not.toHaveProperty('created_at');
    expect(created).not.toHaveProperty('revision');
    expect(patched).not.toHaveProperty('created_at');
    expect(patched.revision).toBe(2);
  });
});
