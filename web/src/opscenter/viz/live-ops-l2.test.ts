import { describe, expect, test } from 'vitest';
import { fleetModel, type FleetSource } from './fleet';
import { burnPerHour, byUrgency, runwayModel, type RunwayAccount } from './runway';
import { laneModel } from './swimlanes';
import { runwayPlan, swimlanePlan, type PlanContext } from './plan';
import type { ChartConfig } from '../cells/analytics/types';

describe('fleetModel', () => {
  const row = (id: string, over: Partial<FleetSource> = {}): FleetSource => ({ session: { id }, tmux_session: `cloude_${id}`, activity_status: 'idle', ...over });

  test('null listing is unknown, not zero', () => {
    const model = fleetModel(null);
    expect(model.total).toBeNull();
    expect(model.rows).toEqual([]);
  });

  test('dead rows are dropped; waiting sorts first; LED signals pass through whole', () => {
    const model = fleetModel([
      row('a', { activity_status: 'idle', label: 'zed' }),
      row('b', { activity_status: 'dead' }),
      row('c', { activity_status: 'working', unread: true, status_source: 'registry', running_model: 'opus', running_context_used_pct: 41.5, subagents_state: 'ok', subagents_running: 2, project_name: 'proj' }),
      row('d', { activity_status: 'question', startup_gate: 'awaiting_startup_prompt' }),
      row('e', { activity_status: null }),
    ]);
    expect(model.total).toBe(4);
    expect(model.rows.map((r) => r.sessionId)).toEqual(['d', 'c', 'a', 'e']);
    expect(model.counts).toEqual({ waiting: 1, working: 1, idle: 1, unknown: 1 });
    const working = model.rows.find((r) => r.sessionId === 'c')!;
    expect(working).toMatchObject({ contextPct: 41.5, subagents: 2, model: 'opus', project: 'proj', led: { status: 'working', unread: true, statusSource: 'registry', startupGate: null } });
    expect(model.rows.find((r) => r.sessionId === 'a')!.name).toBe('zed');
  });

  test('unmeasured context and subagents stay null', () => {
    const only = fleetModel([row('a', { running_context_used_pct: null, subagents_state: 'unmeasured', subagents_running: 3 })]).rows[0]!;
    expect(only.contextPct).toBeNull();
    expect(only.subagents).toBeNull();
  });
});

describe('runway', () => {
  const NOW = Date.parse('2026-09-29T12:00:00Z');
  const pts = (values: (number | null)[], stepMin = 30) => values.map((value, i) => ({ time: new Date(NOW - (values.length - 1 - i) * stepMin * 60_000).toISOString().slice(0, 19), value }));
  const account = (id: string, used: number, resetsInMin: number | null): RunwayAccount => ({
    id, name: id, windows: [{ kind: 'five_hour', label: '5h', used_pct: used, resets_at: resetsInMin === null ? null : new Date(NOW + resetsInMin * 60_000).toISOString() }],
  });

  test('burn slope is percent per hour and ignores a reset drop', () => {
    expect(burnPerHour(pts([10, 20, 30]))).toBeCloseTo(20, 5);
    expect(burnPerHour(pts([80, 90, 5, 15]))).toBeCloseTo(20, 5);
    expect(burnPerHour(pts([30, 30, 30]))).toBe(0);
    expect(burnPerHour(pts([50]))).toBeNull();
    expect(burnPerHour(pts([null, null]))).toBeNull();
    expect(burnPerHour([{ time: '2026-09-29T12:00:00', value: 1 }, { time: '2026-09-29T12:02:00', value: 5 }])).toBeNull();
  });

  test('projects time to limit against the reset', () => {
    const rows = runwayModel([account('a', 60, 180), account('b', 60, 30)], [
      { key: 'a', points: pts([20, 40, 60]) }, { key: 'b', points: pts([20, 40, 60]) },
    ], 'five_hour', NOW);
    expect(rows[0]).toMatchObject({ verdict: 'hits_first', toLimitSeconds: 3600, resetSeconds: 10800 });
    expect(rows[1]).toMatchObject({ verdict: 'resets_first', toLimitSeconds: 3600, resetSeconds: 1800 });
  });

  test('clear when the reset comes first, idle when flat, full at 100', () => {
    const rows = runwayModel([account('a', 20, 30), account('b', 20, 30), account('c', 100, 30)], [
      { key: 'a', points: pts([10, 15, 20]) }, { key: 'b', points: pts([20, 20, 20]) },
    ], 'five_hour', NOW);
    expect(rows.map((r) => r.verdict)).toEqual(['resets_first', 'idle', 'full']);
  });

  test('not measured is unknown, never safe', () => {
    const rows = runwayModel([account('a', 40, 60), account('b', 40, null), { id: 'c', name: 'c', windows: [] }], [
      { key: 'b', points: pts([10, 20, 30]) },
    ], 'five_hour', NOW);
    expect(rows.map((r) => r.verdict)).toEqual(['unknown', 'unknown', 'unknown']);
    expect(rows[2]!.usedPct).toBeNull();
  });

  test('urgency order: full, soonest first, then the rest', () => {
    const base = { window: null, usedPct: 0, resetSeconds: 1, burnPerHour: 1 };
    const rows = byUrgency([
      { ...base, id: 'u', name: 'u', toLimitSeconds: null, verdict: 'unknown' }, { ...base, id: 'l', name: 'l', toLimitSeconds: 7200, verdict: 'hits_first' },
      { ...base, id: 's', name: 's', toLimitSeconds: 60, verdict: 'hits_first' }, { ...base, id: 'f', name: 'f', toLimitSeconds: 0, verdict: 'full' },
    ]);
    expect(rows.map((r) => r.id)).toEqual(['f', 's', 'l', 'u']);
  });
});

describe('laneModel', () => {
  const at = (min: number) => new Date(Date.parse('2026-09-29T10:00:00Z') + min * 60_000).toISOString().slice(0, 19);
  const series = (key: string, values: (number | null)[], filter = key) => ({ key, filter_value: filter, label: key, points: values.map((value, i) => ({ time: at(i * 5), value })) });

  test('folds working, waiting and subagent seconds into blocks and gaps', () => {
    const lanes = laneModel(
      [series('conversation:a', [120, 0, 0, null], 'conv-a'), series('other', [1, 1, 1, 1])],
      [series('conversation:a', [0, 30, 0, null], 'conv-a')],
      [series('conversation:a', [150, 0, 0, null], 'conv-a')],
      (id) => (id === 'conv-a' ? 'my-session' : null),
    );
    expect(lanes).toHaveLength(1);
    const lane = lanes[0]!;
    expect(lane).toMatchObject({ conversationId: 'conv-a', label: 'my-session' });
    expect(lane.blocks.map((b) => b.state)).toEqual(['working', 'waiting', 'idle']);
    expect(lane.blocks[0]!.end - lane.blocks[0]!.start).toBe(5 * 60_000);
    expect(lane.blocks[0]!.subagents).toBeCloseTo(0.5, 5);
    expect(lane.blocks[2]!.subagents).toBe(0);
  });

  test('an unnamed conversation falls back to the series label; nothing measured is no lanes', () => {
    expect(laneModel([series('conversation:z', [10], 'zzz')], [], [], () => null)[0]!.label).toBe('conversation:z');
    expect(laneModel([], [], [], () => null)).toEqual([]);
  });
});

describe('plans', () => {
  const config = { id: 'x', revision: 1, title: 't', enabled: true, viz: 'runway', options: {}, series: [{ metric: 'quota_utilization', group_by: 'account_id' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig;
  const ctx: PlanContext = { now: Date.parse('2026-09-29T12:00:00Z'), timezone: 'UTC', filters: {}, quotaWindow: 'five_hour' };

  test('runway asks for quota percent per account on the quota window', () => {
    const [body] = runwayPlan(config, ctx);
    expect(body).toMatchObject({ metric: 'quota_utilization', operation: 'timeline', group_by: 'account_id', filters: { window: 'five_hour' }, top_n: 10 });
  });

  test('swimlanes ask for three conversation timelines', () => {
    const bodies = swimlanePlan(config, ctx);
    expect(bodies.map((b) => b.metric)).toEqual(['working_seconds', 'waiting_seconds', 'subagent_seconds']);
    for (const body of bodies) expect(body).toMatchObject({ operation: 'timeline', group_by: 'conversation_id', top_n: 8 });
  });
});
