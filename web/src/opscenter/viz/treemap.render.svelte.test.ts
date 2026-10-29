/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-out' } }));
vi.mock('./visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('./query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
const setOption = vi.fn();
vi.mock('./echarts-setup', () => ({
  openChart: () => ({ chart: { setOption }, dispose: () => {} }),
  tokenColors: () => () => '#888888',
}));

import TreemapRenderer from './TreemapRenderer.svelte';
import type { ChartConfig, QueryBody } from '../cells/analytics/types';

const config: ChartConfig = { id: 't1', revision: 1, title: 'token map', enabled: true, viz: 'treemap', options: { measure: 'tokens' },
  series: [{ metric: 'total_tokens' }], filters: {}, range: { mode: 'global', preset: '7d' }, display: { type: 'line' } };

function answer(item: QueryBody) {
  const rows = item.group_by === 'model'
    ? item.filters.provider === 'claude'
      ? [{ key: 'claude-opus-5-5', label: 'Opus 5.5', filter_value: 'claude-opus-5-5', value: 37_000_000 }, { key: 'claude-haiku-4-5', label: 'Haiku 4.5', filter_value: 'claude-haiku-4-5', value: 14_000_000 }]
      : [{ key: 'gpt-6-sol', label: 'GPT-6 Sol', filter_value: 'gpt-6-sol', value: 2_000_000 }]
    : [{ key: 'p1', label: 'atlas', filter_value: 'p1', value: 1_000_000 }];
  return { ok: true, result: { metric: item.metric, operation: 'ranking', unit: 'tokens', resolution: 'auto', series: [], ranking: rows } };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; runQueries.mockReset(); setOption.mockReset(); });

describe('the token map', () => {
  test('reads token rankings and paints the provider and model tree with no grow-in animation', async () => {
    runQueries.mockImplementation(async (items: QueryBody[]) => items.map(answer));
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(TreemapRenderer, { target, props: { config, tier: 'full' } });
    await settle();
    const asked = runQueries.mock.calls[0]?.[0] as QueryBody[];
    expect(asked.map((item) => [item.metric, item.group_by, item.filters.provider])).toEqual([['total_tokens', 'model', 'claude'], ['total_tokens', 'model', 'codex']]);
    const last = setOption.mock.calls.at(-1)?.[0] as { animation: boolean; series: { data: { name: string; value: number; children?: { name: string }[] }[] }[] };
    expect(last.animation).toBe(false);
    const data = last.series[0]!.data;
    expect(data.map((node) => [node.name, node.value])).toEqual([['claude', 51_000_000], ['codex', 2_000_000]]);
    expect(data[0]!.children!.map((node) => node.name)).toEqual(['Opus 5.5', 'Haiku 4.5']);
    expect(setOption.mock.calls.every((call) => (call[0] as { animation: boolean }).animation === false)).toBe(true);
  });
});
