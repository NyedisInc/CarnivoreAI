import { describe, expect, test } from 'vitest';
import type { Annotation } from '../cells/analytics/types';
import { TICKER_LIMIT, feedTokens, hotRows, liveSessionFor, mergeEvents, trendOf, vitalsModel, type LivePayload, type LogEvent } from './noc';

const live: LivePayload = {
  burn: {
    '5m': { tokens_per_minute: 300, estimated_usd_per_hour: 1 },
    '15m': { tokens_per_minute: 200, estimated_usd_per_hour: 2.5 },
    '60m': { tokens_per_minute: 100, estimated_usd_per_hour: 1 },
  },
  cache_hit_ratio_15m: 0.8,
};

describe('vitalsModel', () => {
  test('counts live sessions by state and sums subagents once per session', () => {
    const rows = [
      { activity_status: 'working', session: { id: 'a' }, subagents_state: 'ok', subagents_running: 2 },
      { activity_status: 'working_subagent', session: { id: 'a' }, subagents_state: 'ok', subagents_running: 2 },
      { activity_status: 'question', session: { id: 'b' } },
      { activity_status: 'idle', startup_gate: 'awaiting_startup_prompt', session: { id: 'c' } },
      { activity_status: 'finished_unread', session: { id: 'd' } },
      { activity_status: 'dead', session: { id: 'e' } },
      { activity_status: null, session: { id: 'f' } },
    ];
    const model = vitalsModel(live, rows);
    expect(model.sessions).toEqual({ live: 5, working: 2, waiting: 2, idle: 1 });
    expect(model.subagents).toBe(2);
    expect(model).toMatchObject({ usdPerHour: 2.5, cacheHit: 0.8 });
  });

  test('nothing measured is unknown (null), never zero', () => {
    const model = vitalsModel(null, null);
    expect(model).toEqual({ sessions: null, subagents: null, tokensPerMinute: null, usdPerHour: null, trend: 'unknown', cacheHit: null });
    expect(vitalsModel({ burn: { '15m': { tokens_per_minute: null, estimated_usd_per_hour: null } } }, []).tokensPerMinute).toBeNull();
    expect(vitalsModel(null, [{ subagents_state: 'absent', subagents_running: 0, session: { id: 'x' } }]).subagents).toBeNull();
  });

  test('trend words and their unknowns', () => {
    expect(trendOf(130, 100)).toBe('rising');
    expect(trendOf(70, 100)).toBe('falling');
    expect(trendOf(100, 100)).toBe('steady');
    expect(trendOf(null, 100)).toBe('unknown');
    expect(trendOf(5, 0)).toBe('unknown');
  });
});

describe('vitals tokens per minute comes from the stats feed', () => {
  const bars = (totals: (number | null)[]) => ({ v: 1, rev: 1, window: '1h' as const, bucket_seconds: 60, start: 0, now: 0, state: 'ok',
    in: totals.map((t) => (t === null ? null : t - 10)), out: totals.map((t) => (t === null ? null : 10)),
    totals: null, rate: { span_seconds: 60, fresh: 1, cache_write: 2, cache_read: 3, out: 4 }, sources: [] });

  test('the figure is the feed rate (in + out) per minute, not the 15 minute burn', () => {
    const model = vitalsModel(live, [], bars([100, 100]));
    expect(model.tokensPerMinute).toBe((1 + 2 + 3 + 4) * 60);
    expect(model.tokensPerMinute).not.toBe(200);
  });

  test('trend compares the last five minute bars with the hour, skipping gaps', () => {
    const hour = Array<number | null>(55).fill(100).concat([400, 400, 400, 400, 400, 0]);
    expect(vitalsModel(null, [], bars(hour)).trend).toBe('rising');
    expect(feedTokens(bars([null, null, 50, 1])).hour).toBe(50);
    expect(feedTokens(bars([null, null, 7])).recent).toBeNull();
  });

  test('no feed or no rate is unknown, never the burn and never zero', () => {
    expect(vitalsModel(live, [], null).tokensPerMinute).toBeNull();
    expect(vitalsModel(live, [], { ...bars([1]), rate: null }).tokensPerMinute).toBeNull();
  });
});

describe('hotRows', () => {
  const top = (id: string, tokens: number, cost: number | null) => ({ conversation_id: id, provider: 'claude', project: `p-${id}`, model: 'opus', tokens, estimated_cost_usd: cost });

  test('sorts largest first and sizes each bar against the largest', () => {
    const rows = hotRows({ top_conversations_15m: [top('a', 50, null), top('b', 100, 1.5)] });
    expect(rows.map((row) => row.key)).toEqual(['claude:b', 'claude:a']);
    expect(rows.map((row) => row.share)).toEqual([1, 0.5]);
    expect(rows[1]!.costUsd).toBeNull();
  });

  test('nothing read or measured is an empty table', () => {
    expect(hotRows(null)).toEqual([]);
    expect(hotRows({})).toEqual([]);
    expect(hotRows({ top_conversations_15m: [top('z', 0, null)] })[0]!.share).toBe(0);
  });

  test('a row opens the session whose conversation id is exactly its own', () => {
    const one = { activity_status: 'idle', project_name: 'shared', claude_session_uuid: 'conv-a' };
    const twin = { activity_status: 'idle', project_name: 'shared', claude_session_uuid: 'conv-b' };
    const dead = { activity_status: 'dead', project_name: 'shared', claude_session_uuid: 'conv-c' };
    expect(liveSessionFor('conv-a', [one, twin])).toBe(one);
    expect(liveSessionFor('conv-b', [one, twin, dead])).toBe(twin);
    expect(liveSessionFor('conv-c', [one, dead])).toBeNull();
    expect(liveSessionFor('conv-b', [twin, { ...twin }])).toBeNull();
    expect(liveSessionFor('conv-z', [one, { activity_status: 'idle', claude_session_uuid: null }])).toBeNull();
    expect(liveSessionFor('shared', [one])).toBeNull();
    expect(liveSessionFor(null, [one])).toBeNull();
    expect(liveSessionFor('conv-a', null)).toBeNull();
  });

  test('a hot row carries its conversation id', () => {
    expect(hotRows({ top_conversations_15m: [top('conv-a', 5, null)] })[0]!.conversationId).toBe('conv-a');
  });
});

describe('mergeEvents', () => {
  const log = (id: number, at: number, kind = 'session_created'): LogEvent => ({ id, occurred_at: at, kind, subject: `s${id}` });
  const mark = (id: string, at: number, kind: Annotation['kind'] = 'rule'): Annotation => ({ id, revision: 1, occurred_at: at, kind, label: `m${id}` });

  test('merges both sources newest first with stable ties', () => {
    const rows = mergeEvents([log(1, 10), log(2, 30, 'tripwire_fired')], [mark('x', 20), mark('y', 30, 'manual')]);
    expect(rows.map((row) => row.key)).toEqual(['a' + 'y', 'e2', 'ax', 'e1']);
    expect(rows[0]).toMatchObject({ kindKey: 'events.kind.mark_manual', subject: 'my' });
    expect(rows[1]!.kindKey).toBe('events.kind.tripwire_fired');
  });

  test('is bounded, by default and by argument', () => {
    const many = Array.from({ length: 80 }, (_, at) => log(at, at));
    expect(mergeEvents(many, [])).toHaveLength(TICKER_LIMIT);
    expect(mergeEvents(many, [])[0]!.at).toBe(79);
    expect(mergeEvents(many, [], 3)).toHaveLength(3);
    expect(mergeEvents([], [])).toEqual([]);
  });
});
