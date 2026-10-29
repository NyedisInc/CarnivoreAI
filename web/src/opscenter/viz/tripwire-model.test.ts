import { describe, expect, it } from 'vitest';
import { alarmFor, applyFrame, seriesUnit, thresholdLines, toDisplay, toStored, tripwireQuery, type Tripwire } from './tripwire-model';
import type { ChartConfig } from '../cells/analytics/types';

const wire = (over: Partial<Tripwire> = {}): Tripwire => ({
  id: 'a', chart_id: 'c1', name: 'burn', query: { metric: 'estimated_cost_nano_usd' }, window_minutes: 15, comparator: '>',
  threshold: 5e9, for_minutes: 5, cooldown_minutes: 30, enabled: true, state: 'ok', since: 1, last_value: null, ...over,
});

describe('unit conversion', () => {
  it('turns a USD threshold into nano-USD and back', () => {
    expect(toStored(2.5, 'nano_usd')).toBe(2_500_000_000);
    expect(toStored(0.1, 'nano_usd/second')).toBe(100_000_000);
    expect(toDisplay(2_500_000_000, 'nano_usd')).toBe(2.5);
  });
  it('turns a percent threshold into a stored fraction and back', () => {
    expect(toStored(80, 'fraction')).toBe(0.8);
    expect(toDisplay(0.8, 'fraction')).toBe(80);
  });
  it('leaves other units alone', () => {
    expect(toStored(1500, 'tokens')).toBe(1500);
    expect(toDisplay(42, 'percent')).toBe(42);
  });
});

describe('frame to widget state', () => {
  it('sets state, value, threshold and comparator from a firing frame', () => {
    const next = applyFrame([wire()], { id: 'a', state: 'firing', value: 9e9, threshold: 5e9, comparator: '>' });
    expect(next[0]).toMatchObject({ state: 'firing', last_value: 9e9 });
    expect(alarmFor(next, 'c1').state).toBe('firing');
  });
  it('resolves on an ok frame and ignores unknown ids or states', () => {
    const list = [wire({ state: 'firing' })];
    expect(applyFrame(list, { id: 'a', state: 'ok', value: 1 })[0]?.state).toBe('ok');
    expect(applyFrame(list, { id: 'zzz', state: 'ok' })).toBe(list);
    expect(applyFrame(list, { id: 'a', state: 'weird' })).toBe(list);
  });
  it('ranks firing above unknown above ok and skips disabled or other charts', () => {
    const list = [wire({ id: 'a', state: 'ok' }), wire({ id: 'b', state: 'unknown' }), wire({ id: 'c', state: 'firing', chart_id: 'c2' }), wire({ id: 'd', state: 'firing', enabled: false })];
    expect(alarmFor(list, 'c1')).toMatchObject({ state: 'unknown' });
    expect(alarmFor(list, 'c2').state).toBe('firing');
    expect(alarmFor([], 'c1')).toEqual({ state: 'ok', wire: null });
  });
});

describe('threshold lines and query', () => {
  it('draws lines in the chart axis unit, only for the same metric and never indexed', () => {
    const list = [wire(), wire({ id: 'b', query: { metric: 'total_tokens' }, threshold: 900 })];
    expect(thresholdLines(list, 'c1', 'estimated_cost_nano_usd', 'nano_usd', false)).toEqual([5]);
    expect(thresholdLines(list, 'c1', 'total_tokens', 'tokens', false)).toEqual([900]);
    expect(thresholdLines(list, 'c1', 'total_tokens', 'tokens', true)).toEqual([]);
  });
  it('builds a rangeless summary query from the series', () => {
    const config = { id: 'c1', revision: 1, title: 't', enabled: true, series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }], filters: { model: 'x' }, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig;
    const query = tripwireQuery(config, config.series[0]!, { now: 0, timezone: 'UTC', filters: {} });
    expect(query).toMatchObject({ metric: 'total_tokens', operation: 'summary', filters: { model: 'x' } });
    for (const key of ['from', 'to', 'group_by', 'comparison', 'top_n']) expect(query).not.toHaveProperty(key);
  });
  it('appends the transform tail to the catalog unit', () => {
    expect(seriesUnit({ m: 'nano_usd' }, { metric: 'm', transform: 'rate' })).toBe('nano_usd/second');
    expect(seriesUnit({ m: 'tokens' }, { metric: 'm' })).toBe('tokens');
  });
});
