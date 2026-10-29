/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('./visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const { runQueries, canvases, changed, feed, listing } = vi.hoisted(() => ({
  runQueries: vi.fn(), changed: vi.fn(),
  canvases: [] as { results: { series: { key: string; label: string; filter_value?: string | null }[] }[]; lookFor: (key: string) => { color: string; dashed?: boolean } | null }[],
  feed: { data: null as unknown, failure: '', fetchedAt: null as number | null },
  listing: { data: [] as unknown[] },
}));
vi.mock('./query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('../cells/analytics/ChartCanvas.svelte', () => ({ default: (_anchor: unknown, props: (typeof canvases)[number]) => { canvases.push(props); } }));
vi.mock('./VizSettings.svelte', () => ({ default: () => {} }));
vi.mock('../layout-editor/editor.svelte', () => ({ changeAnalyticsConfig: (...args: unknown[]) => changed(...args), layoutEditor: { active: false } }));
vi.mock('./noc-feed.svelte', () => ({ live: feed, watchLive: () => () => {} }));
vi.mock('../api', () => ({ sessions: listing, openSession: vi.fn() }));

import { setLocale } from '../../lib/i18n/index.svelte';
import type { ChartConfig, QueryResult } from '../cells/analytics/types';
import AgentsRenderer from './AgentsRenderer.svelte';
import { agentsUpgrade } from '../cells/analytics/agents-upgrade';
import { analytics } from '../cells/analytics/state.svelte';
import ChartLegend from '../cells/analytics/ChartLegend.svelte';
import { agentChart, agentColor, agentWindow, agentsPlan, liveAgents } from './agents';

setLocale('en');

const CONFIG: ChartConfig = { id: 'a', revision: 1, title: 'tokens per agent', enabled: true, viz: 'agents', options: {},
  series: [{ metric: 'total_tokens', operation: 'timeline', group_by: 'conversation_id' }], filters: {},
  range: { mode: 'global', preset: '24h' }, display: { type: 'line', legend: true } };
const CTX = { now: Date.UTC(2026, 9, 23, 12), timezone: 'UTC', filters: {} };

function answer(count: number): QueryResult {
  const named = Array.from({ length: Math.min(count, 8) }, (_, at) => ({
    key: `conversation:h${at}`, label: `agent ${at}`, filter_value: `00000000-0000-4000-8000-00000000000${at}`,
    points: [{ time: '2026-10-23T11:00:00Z', value: 100 - at }, { time: '2026-10-23T11:30:00Z', value: 50 }] }));
  const other = count > 8 ? [{ key: 'other', label: 'Other', filter_value: null, points: [{ time: '2026-10-23T11:00:00Z', value: 7 }, { time: '2026-10-23T11:30:00Z', value: 9 }] }] : [];
  return { metric: 'total_tokens', operation: 'timeline', unit: 'tokens', resolution: 'hour', series: [...named, ...other] };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

const mounted: ReturnType<typeof mount>[] = [];
async function show(config: ChartConfig, result: QueryResult): Promise<HTMLElement> {
  runQueries.mockImplementation(async (items: unknown[]) => items.map(() => ({ ok: true, result })));
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(AgentsRenderer, { target, props: { config, tier: 'panel' } }));
  await settle();
  return target;
}

beforeEach(() => { canvases.length = 0; feed.data = null; listing.data = []; changed.mockReset(); });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); runQueries.mockReset(); });

describe('the chart', () => {
  test('asks for the top eight agents of the window in one rolling grouped timeline', () => {
    const [body] = agentsPlan({ ...CONFIG, range: { mode: 'global', preset: '7d' } }, { ...CTX, quotaWindow: undefined });
    expect(body).toMatchObject({ metric: 'total_tokens', operation: 'timeline', group_by: 'conversation_id', top_n: 8, rolling: '7d' });
    expect(agentsPlan(CONFIG, CTX)[0]).toMatchObject({ rolling: '24h' });
    expect(agentWindow({ range: { mode: 'global', preset: '30d' } })).toBe('24h');
  });

  test('nine agents draw eight named lines and one "other agents" line in a quiet token, never an id', async () => {
    await show(CONFIG, answer(9));
    const drawn = canvases.at(-1)!;
    const series = drawn.results[0]!.series;
    expect(series.map((item) => item.label)).toEqual([...Array.from({ length: 8 }, (_, at) => `agent ${at}`), 'other agents']);
    expect(JSON.stringify(series.map((item) => item.label))).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    expect(drawn.lookFor('other')).toEqual({ color: '--oc-text-dim', dashed: true });
    expect(drawn.lookFor('conversation:h3')).toEqual({ color: agentColor('00000000-0000-4000-8000-000000000003'), dashed: false });
  });

  test('eight or fewer agents add no "other agents" line', () => {
    expect(agentChart(answer(8)).lines.some((line) => line.other)).toBe(false);
    expect(agentChart(answer(3)).lines).toHaveLength(3);
  });

  test('an agent with nothing in the newest bucket yet is not drawn dropping to zero, one with usage there keeps it', () => {
    const base = answer(2);
    const grow = (last: [number, number]) => ({ ...base, series: base.series.map((item, at) => ({ ...item, points: [...item.points, { time: '2026-10-23T12:00:00Z', value: last[at]! }] })) });
    expect(agentChart(grow([0, 0])).result!.series.every((item) => item.points.at(-1)!.time === '2026-10-23T11:30:00Z')).toBe(true);
    const mixed = agentChart(grow([0, 6000])).result!.series;
    expect(mixed.map((item) => item.points.at(-1)!.value)).toEqual([50, 6000]);
  });

  test('the legend wraps and never pages', async () => {
    await show(CONFIG, answer(9));
    expect(canvases.at(-1)).toMatchObject({ wrapLegend: true });
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ChartLegend, { target, props: { items: Array.from({ length: 9 }, (_, at) => ({ name: `agent ${at}`, color: 'red', on: true })), onToggle: () => {}, wrap: true } }));
    await settle();
    expect(target.querySelector('.chart-legend__track--wrap')).not.toBeNull();
    expect(target.querySelector('.chart-legend__pager:not(.chart-legend__pager--probe)')).toBeNull();
    expect(target.querySelectorAll('.chart-legend__cell--off')).toHaveLength(0);
  });

  test('pushed usage re-asks the rolling query without a reload', async () => {
    await show(CONFIG, answer(2));
    expect(runQueries).toHaveBeenCalledTimes(1);
    analytics.metricTicks = { total_tokens: Date.now() + 1 };
    await settle();
    expect(runQueries).toHaveBeenCalledTimes(2);
    expect(runQueries.mock.calls[1]![0]).toEqual(runQueries.mock.calls[0]![0]);
  });

  test('the window toggle marks the saved window and saves the pick on the chart', async () => {
    const target = await show({ ...CONFIG, range: { mode: 'global', preset: '7d' } }, answer(2));
    const radios = [...target.querySelectorAll<HTMLButtonElement>('[data-agents-window] [role=radio]')];
    expect(radios.map((radio) => [radio.textContent, radio.getAttribute('aria-checked')])).toEqual([['1h', 'false'], ['24h', 'false'], ['1w', 'true']]);
    radios[0]!.click();
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ range: expect.objectContaining({ preset: '1h', zoom: null }) }));
    radios[2]!.click();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(runQueries.mock.calls[0]![0][0]).toMatchObject({ rolling: '7d' });
  });
});

describe('the live list', () => {
  const live = (rows: [string, string, number][]) => ({ agents_5m: rows.map(([id, name, perMinute]) => ({ conversation_id: id, name, tokens: perMinute * 5, tokens_per_minute: perMinute })) });
  const session = (uuid: string, activity = 'working') => ({ claude_session_uuid: uuid, activity_status: activity });

  test('shows running agents with tokens, highest first, hides zero and stopped, in the chart hue', async () => {
    feed.data = live([['c1', 'slow one', 120], ['c2', 'fast one', 9000], ['c3', 'gone one', 50000], ['c4', 'zero one', 0], ['c5', 'mid one', 1500]]);
    listing.data = [session('c1'), session('c2'), session('c3', 'dead'), session('c4'), session('c5', 'idle')];
    const target = await show(CONFIG, answer(2));
    const rows = [...target.querySelectorAll<HTMLElement>('[data-agents-live] [data-agent]')];
    expect(rows.map((row) => row.querySelector('.viz-agents__name')!.textContent)).toEqual(['fast one', 'mid one', 'slow one']);
    expect(rows.map((row) => row.querySelector('.viz-agents__value')!.textContent)).toEqual(['9k/min', '1.5k/min', '120/min']);
    expect(rows[0]!.querySelector<HTMLElement>('.viz-agents__swatch')!.getAttribute('style')).toContain(agentColor('c2'));
    expect(target.textContent).not.toContain('gone one');
  });

  test('says one plain line when nothing is using tokens', async () => {
    feed.data = live([['c1', 'quiet', 0]]);
    listing.data = [session('c1')];
    const target = await show(CONFIG, answer(2));
    expect(target.querySelectorAll('[data-agent]')).toHaveLength(0);
    expect(target.querySelector('.viz-agents__idle')!.textContent).toBe('no running agent is using tokens right now');
  });

  test('liveAgents ranks by rate and the top row fills the bar', () => {
    const rows = liveAgents(live([['a', 'a', 10], ['b', 'b', 40]]) as never, [session('a'), session('b')] as never);
    expect(rows.map((row) => [row.name, row.share])).toEqual([['b', 1], ['a', 0.25]]);
  });
});

describe('the upgrade of the old card', () => {
  const old: ChartConfig = { id: 'k', revision: 4, title: 'tokens by agent kind', enabled: true, series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'agent_kind' }], filters: {}, range: { mode: 'global' }, display: { type: 'bar', legend: true } };

  test('keeps the id and revision, becomes tokens per agent, and keeps a title the owner changed', () => {
    expect(agentsUpgrade(old)).toMatchObject({ id: 'k', revision: 4, viz: 'agents', title: 'tokens per agent', series: [{ group_by: 'conversation_id', operation: 'timeline' }] });
    expect(agentsUpgrade({ ...old, title: 'my burners' })?.title).toBe('my burners');
  });

  test('leaves every other card alone, itself included once upgraded', () => {
    expect(agentsUpgrade({ ...old, series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }] })).toBeNull();
    expect(agentsUpgrade(agentsUpgrade(old)!)).toBeNull();
  });
});
