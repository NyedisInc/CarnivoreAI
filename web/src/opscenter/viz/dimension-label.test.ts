import { describe, expect, it } from 'vitest';
import { dimensionLabel, labelResult } from './dimension-label';
import { hotTag, type HotRow } from './noc';
import { formatDuration } from './format';
import { cacheHitRate, displayHeadline } from '../cells/analytics/headline';
import type { QueryBody, QueryResult } from '../cells/analytics/types';

const body = (metric: string, group_by?: string): QueryBody => ({ metric, operation: 'ranking', from: 'a', to: 'b', timezone: 'UTC', resolution: 'auto', filters: {}, ...(group_by ? { group_by } : {}) });

describe('dimension labels (#1157: no raw keys on a chart)', () => {
  it('names stop reasons and agent kinds from the catalog', () => {
    expect(dimensionLabel('stop_reasons', 'key', 'end_turn', 'end_turn')).toBe('finished the turn');
    expect(dimensionLabel('total_tokens', 'agent_kind', 'subagent', 'subagent')).toBe('subagents');
  });
  it('reads an unknown key\'s underscores as spaces and leaves tool names and other groupings alone', () => {
    expect(dimensionLabel('stop_reasons', 'key', 'model_context_window_exceeded', 'model_context_window_exceeded')).toBe('model context window exceeded');
    expect(dimensionLabel('tool_calls', 'key', 'WebFetch', 'WebFetch')).toBe('WebFetch');
    expect(dimensionLabel('total_tokens', 'model', 'claude-opus-5-5', 'Opus 5.5')).toBe('Opus 5.5');
  });
  it('renames ranking rows and series of an answer, and returns any other answer untouched', () => {
    const result = { metric: 'stop_reasons', operation: 'ranking', unit: 'events', resolution: 'auto',
      series: [{ key: 'tool_use', label: 'tool_use', points: [] }],
      ranking: [{ key: 'end_turn', label: 'end_turn', filter_value: 'end_turn', value: 3 }] } as QueryResult;
    const named = labelResult(body('stop_reasons', 'key'), result);
    expect(named.ranking?.[0]?.label).toBe('finished the turn');
    expect(named.series[0]?.label).toBe('called a tool');
    expect(labelResult(body('total_tokens', 'project'), result)).toBe(result);
  });
});

describe('hot rows sharing a project get a tag', () => {
  const row = (id: string, project: string): HotRow => ({ key: id, conversationId: id, project, model: 'Opus 5.5', provider: 'claude', tokens: 1, costUsd: null, share: 1 });
  it('tags only repeated projects, preferring the live session title', () => {
    const rows = [row('abc123ffff', 'atlas'), row('def456ffff', 'atlas'), row('0000000000', 'orbit')];
    expect(hotTag(rows[0]!, rows, null)).toBe('abc123');
    expect(hotTag(rows[1]!, rows, 'fix the ledger')).toBe('fix the ledger');
    expect(hotTag(rows[2]!, rows, null)).toBe('');
  });
});

describe('one number style', () => {
  it('drops a zero minor unit from a duration', () => {
    expect(formatDuration(60)).toBe('1m');
    expect(formatDuration(600)).toBe('10m');
    expect(formatDuration(6000)).toBe('1h 40m');
    expect(formatDuration(7200)).toBe('2h');
    expect(formatDuration(61)).toBe('1m 1s');
  });
  it('prints a headline in the SI style the rest of the kit uses', () => {
    expect(displayHeadline(23_240_000, 'tokens')).toBe('23.2M');
    expect(displayHeadline(176_250, 'tokens')).toBe('176k');
    expect(displayHeadline(16_870_000_000, 'nano_usd')).toBe('$16.87');
  });
  it('computes the cache hit rate over every input token, unknown when a part is unmeasured', () => {
    expect(cacheHitRate(90, 5, 5)).toBeCloseTo(0.9);
    expect(cacheHitRate(90, null, 5)).toBeNull();
    expect(cacheHitRate(0, 0, 0)).toBeNull();
  });
});
