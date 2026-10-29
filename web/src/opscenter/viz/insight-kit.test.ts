import { describe, expect, test } from 'vitest';
import type { ChartConfig } from '../cells/analytics/types';
import { FLOW_MAX_QUERIES, FLOW_TOP, flowDepth, flowDrills, flowGraph, flowLevelsPlan, flowLinksPlan } from './flow';
import { COLLECTOR_STALE_SECONDS, healthModel, scaleBytes } from './health';
import { impactDays, impactMetric, impactModel, impactPath, pickMarker, type ImpactPayload } from './impact';
import type { PlanContext } from './plan';
import { scatterPath, scatterPoints, type ConversationRow } from './scatter';
import type { RankRow } from './shape';

const NOW = Date.parse('2026-09-29T12:00:00Z');
const ctx: PlanContext = { now: NOW, timezone: 'UTC', filters: {} };
const config = (options: Record<string, unknown> = {}): ChartConfig => ({
  id: 'x', revision: 1, title: 'flow', enabled: true, viz: 'flow', options, series: [{ metric: 'total_tokens' }], filters: {}, range: { mode: 'global', preset: '7d' }, display: { type: 'line' },
});
const row = (key: string, value: number | null, filter: string | null = key): RankRow => ({ key, label: key.toUpperCase(), filter_value: filter, value });

describe('flow', () => {
  const levels = [[row('a1', 10), row('a2', 6)], [row('m1', 9), row('m2', 7)], [row('k1', 12), row('k2', 4)]];

  test('the plan stays inside its query bound and filters each drill by its parent', () => {
    expect(flowLevelsPlan(config(), ctx).map((body) => body.group_by)).toEqual(['account_id', 'model', 'agent_kind']);
    const many = [0, 1, 2].map(() => ['p', 'q', 'r', 's', 't'].map((key) => row(key, 5)));
    const drills = flowDrills(many);
    expect(drills).toHaveLength(9);
    expect(flowLevelsPlan(config(), ctx).length + flowLinksPlan(config(), ctx, drills).length).toBeLessThanOrEqual(FLOW_MAX_QUERIES);
    const plan = flowLinksPlan(config(), ctx, flowDrills(levels));
    expect(plan[0]).toMatchObject({ operation: 'ranking', group_by: 'model', top_n: FLOW_TOP, filters: { account_id: 'a1' } });
    expect(plan.find((body) => body.group_by === 'project')?.filters).toMatchObject({ agent_kind: 'k1' });
  });

  test('cost measure asks for cost and undrillable or empty nodes are skipped', () => {
    expect(flowLevelsPlan(config({ measure: 'cost' }), ctx)[0]!.metric).toBe('estimated_cost_nano_usd');
    expect(flowDrills([[row('a', 3, null), row('b', 0), row('other', 4, null)], [], []])).toEqual([]);
  });

  test('links fold whatever leaves a level top set into other and sum per pair', () => {
    const drills = flowDrills(levels);
    const answers = drills.map((drill) => {
      if (drill.level === 0) return [row('m1', 5), row('zz', 2), row('other', 1, null)];
      if (drill.level === 1) return [row('k1', 6)];
      return [row('p1', 8), row('p2', 3), row('p3', 2), row('p4', 1)];
    });
    const graph = flowGraph(levels, drills, answers, 'other');
    const value = (source: string, target: string) => graph.links.find((link) => link.source === source && link.target === target)?.value;
    expect(value('0:a1', '1:m1')).toBe(5);
    expect(value('0:a1', '1:other')).toBe(3);
    expect(value('2:k1', '3:other')).toBeGreaterThan(0);
    expect(graph.nodes.find((node) => node.id === '1:other')?.name).toBe('other');
    expect(graph.nodes.every((node) => graph.links.some((link) => link.source === node.id || link.target === node.id))).toBe(true);
    expect(graph.nodes.filter((node) => node.level === 3 && node.id !== '3:other').length).toBeLessThanOrEqual(FLOW_TOP);
  });

  test('depth cuts columns and drops the links that leave them', () => {
    const drills = flowDrills(levels);
    const graph = flowGraph(levels, drills, drills.map(() => [row('m1', 4)]), 'other');
    const two = flowDepth(graph, 2);
    expect(Math.max(...two.nodes.map((node) => node.level))).toBe(1);
    expect(two.links.every((link) => link.target.startsWith('1:'))).toBe(true);
  });

  test('a failed drill leaves nothing to draw rather than a zero link', () => {
    expect(flowGraph(levels, flowDrills(levels), flowDrills(levels).map(() => null), 'other')).toEqual({ nodes: [], links: [] });
  });
});

describe('scatter', () => {
  const rows: ConversationRow[] = [
    { conversation_id: 'a', project: 'p', model: 'm', tokens: 100, cost_nano_usd: 2_000_000_000, first_minute: 0, last_minute: 600, duration_seconds: 660 },
    { conversation_id: 'b', project: 'p', model: 'm', tokens: 400, cost_nano_usd: 1_000_000_000, first_minute: 0, last_minute: 0, duration_seconds: 10 },
    { conversation_id: 'c', project: 'p', model: 'm', tokens: 50, cost_nano_usd: null, first_minute: 0, last_minute: 0, duration_seconds: 60 },
  ];

  test('dots are priced rows on log-safe axes and sized by root tokens', () => {
    const { points, unpriced } = scatterPoints(rows, 4, 20);
    expect(unpriced).toBe(1);
    expect(points.map((point) => point.id)).toEqual(['a', 'b']);
    expect(points[0]).toMatchObject({ minutes: 11, usd: 2, size: 12 });
    expect(points[1]).toMatchObject({ minutes: 1, size: 20 });
    expect(scatterPoints([]).points).toEqual([]);
  });

  test('the path carries the range, the cap and only the filters the endpoint takes', () => {
    const path = scatterPath(config(), { ...ctx, filters: { provider: 'claude', project: 'abc', agent_kind: 'main' } });
    const params = new URL(path, 'http://x').searchParams;
    expect(path.startsWith('/stats/conversations?')).toBe(true);
    expect(params.get('limit')).toBe('500');
    expect(params.get('provider')).toBe('claude');
    expect(params.get('agent_kind')).toBeNull();
    expect(new Date(params.get('to')!).getTime() - new Date(params.get('from')!).getTime()).toBe(7 * 86400_000);
  });
});

describe('impact', () => {
  test('the newest past marker is the default and a chosen one always wins', () => {
    const markers = [{ id: 'old', occurred_at: 10 }, { id: 'new', occurred_at: 50 }, { id: 'future', occurred_at: 900 }];
    expect(pickMarker(markers, '', 100)).toBe('new');
    expect(pickMarker(markers, 'old', 100)).toBe('old');
    expect(pickMarker([], '', 100)).toBeNull();
  });

  test('options are held to what the server accepts and the path names all three', () => {
    expect(impactMetric(config({ metric: 'working_seconds' }))).toBe('estimated_cost_nano_usd');
    expect(impactMetric(config({ metric: 'total_tokens' }))).toBe('total_tokens');
    expect(impactDays(config({ days: 99 }))).toBe(7);
    expect(impactDays(config({ days: 14 }))).toBe(14);
    expect(impactPath('id-1', 'total_tokens', 3)).toBe('/stats/impact?annotation_id=id-1&metric=total_tokens&days=3');
  });

  const payload = (patch: Partial<ImpactPayload> = {}): ImpactPayload => ({
    annotation: { id: 'x', label: 'rule change', kind: 'rule', reference: null, occurred_at: 1 }, metric: 'total_tokens', unit: 'tokens', days: 7,
    before: { from: 0, to: 1, n: 8, conversations: 8, median: 100 }, after: { from: 1, to: 2, n: 9, conversations: 9, median: 150, partial: false },
    delta: { absolute: 50, percent: 0.5 }, interval: { low: 10, high: 90, level: 0.95, iterations: 1000, seed: 1 },
    mix: { distance: 0.4, shifted: true, models: [{ model: 'opus', before: 0.1, after: 0.6 }] }, verdict: 'higher', subsampled: false, ...patch,
  });

  test('the model carries the verdict, interval and the mix mover only when the mix shifted', () => {
    const model = impactModel(payload())!;
    expect(model).toMatchObject({ verdict: 'higher', before: 100, after: 150, change: 0.5, low: 10, high: 90, nBefore: 8, nAfter: 9, mover: { model: 'opus' } });
    expect(impactModel(payload({ mix: { distance: 0.1, shifted: false, models: [] } }))!.mover).toBeNull();
    const thin = impactModel(payload({ interval: null, verdict: 'insufficient', delta: { absolute: null, percent: null } }))!;
    expect(thin).toMatchObject({ verdict: 'insufficient', low: null, high: null, change: null });
    expect(impactModel(null)).toBeNull();
  });
});

describe('health', () => {
  const coverage = (patch: Record<string, unknown> = {}) => ({
    freshness_seconds: 30, quality_rows: 2, unknown_cost_rows: 1, db_bytes: 3_500_000,
    sources: [{ status: 'ok', quality: 'ok', count: 40 }, { status: 'missing', quality: 'missing', count: 3 }],
    collector: { state: 'ok', last_success: 1000, backfill_running: true, collector: { known_sources: 43, pending_sources: 5 } }, ...patch,
  });

  test('a fresh pass is running, an old one is stale, and the backlog and missing sources are counted', () => {
    const fresh = healthModel(coverage(), 1010);
    expect(fresh).toMatchObject({ state: 'ok', tone: 'ok', passAgeSeconds: 10, pendingSources: 5, knownSources: 43, replaying: true, missingSources: 3, dbBytes: 3_500_000 });
    const stale = healthModel(coverage(), 1000 + COLLECTOR_STALE_SECONDS + 1);
    expect(stale).toMatchObject({ state: 'stale', tone: 'bad' });
  });

  test('what was never measured stays null instead of reading zero or fine', () => {
    const empty = healthModel(null, 1000);
    expect(empty).toMatchObject({ state: null, tone: 'unknown', passAgeSeconds: null, pendingSources: null, replaying: null, missingSources: null, dbBytes: null });
    expect(healthModel(coverage({ collector: { state: 'weird' } }), 1000).state).toBeNull();
    expect(healthModel(coverage({ collector: { state: 'error' } }), 1000).tone).toBe('bad');
    expect(healthModel(coverage({ collector: { state: 'disabled' } }), 1000).tone).toBe('warn');
  });

  test('bytes scale to kb, mb and gb with one decimal', () => {
    expect(scaleBytes(2048)).toEqual({ unit: 'kb', value: 2 });
    expect(scaleBytes(3_500_000)).toEqual({ unit: 'mb', value: 3.3 });
    expect(scaleBytes(5 * 1024 ** 3)).toEqual({ unit: 'gb', value: 5 });
  });
});
