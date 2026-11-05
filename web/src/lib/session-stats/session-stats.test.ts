import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../subagents/subagents', () => ({ fetchSubagents: vi.fn(async () => ({ state: 'ok', subagents: [] })) }));
vi.mock('../background-work/background-work', () => ({ fetchBackgroundWork: vi.fn(async () => ({ state: 'ok', processes: [] })) }));

import { fetchBackgroundWork } from '../background-work/background-work';
import { fetchSubagents } from '../subagents/subagents';
import { contextGauge, contextPercentSpoken, contextUsedPct, modelShortName } from './context-gauge';
import { sessionUsageLabels } from '../../opscenter/api/session-usage.svelte';
import type { SessionTokenUsage } from '../../opscenter/api/types';
import { readSessionWork, resetSessionWork, SESSION_WORK_REUSE_MS } from './session-work';

describe('contextGauge', () => {
  it('steps on the foot bar ladder and clamps', () => {
    expect([10, 25, 50, 80, 95].map((p) => contextGauge(p)?.scale)).toEqual([1, 2, 3, 4, 5]);
    expect(contextGauge(140)?.pct).toBe(100);
    expect(contextGauge(-4)?.pct).toBe(0);
  });
  it('is null for anything unmeasured, never zero', () => {
    for (const v of [null, undefined, 'x', Number.NaN, Infinity]) expect(contextGauge(v)).toBeNull();
  });
});

describe('modelShortName', () => {
  it('drops the vendor prefix and blanks a non-string', () => {
    expect(modelShortName(' claude-opus-5-5 ')).toBe('opus-5-5');
    expect(modelShortName(null)).toBe('');
  });
});

describe('readSessionWork', () => {
  beforeEach(() => { resetSessionWork(); vi.mocked(fetchSubagents).mockClear(); vi.mocked(fetchBackgroundWork).mockClear(); });
  afterEach(() => resetSessionWork());

  it('two surfaces on one key share one request per list', async () => {
    const [a, b] = await Promise.all([readSessionWork('s', 'k', { nowMs: 0 }), readSessionWork('s', 'k', { nowMs: 10 })]);
    expect(a).toBe(b);
    expect(fetchSubagents).toHaveBeenCalledTimes(1);
    expect(fetchBackgroundWork).toHaveBeenCalledTimes(1);
  });
  it('re-reads on a new key, after the reuse window, and when forced', async () => {
    await readSessionWork('s', 'k', { nowMs: 0 });
    await readSessionWork('s', 'k2', { nowMs: 1 });
    await readSessionWork('s', 'k2', { nowMs: SESSION_WORK_REUSE_MS + 5 });
    await readSessionWork('s', 'k2', { nowMs: SESSION_WORK_REUSE_MS + 6, force: true });
    expect(fetchSubagents).toHaveBeenCalledTimes(4);
  });
  it('keeps sessions apart', async () => {
    await readSessionWork('a', 'k', { nowMs: 0 });
    await readSessionWork('b', 'k', { nowMs: 0 });
    expect(fetchSubagents).toHaveBeenCalledTimes(2);
  });
});

describe('one derivation of the used percent', () => {
  it('contextUsedPct is the unrounded share of the window, clamped, null when unmeasured', () => {
    expect(contextUsedPct(415000, 1000000)).toBe(41.5);
    expect(contextUsedPct(414600, 1000000)).toBeCloseTo(41.46);
    expect(contextUsedPct(2000000, 1000000)).toBe(100);
    expect(contextUsedPct(null, 1000000)).toBeNull();
    expect(contextUsedPct(5, 0)).toBeNull();
    expect(contextPercentSpoken(41.46)).toBe(41);
  });
  it('the foot bar label says the figure the sidebar row speaks, rounded once', () => {
    const usage = {
      state: 'ok', context_remaining_pct: 58.5, context_used_tokens: 414600, context_window_tokens: 1000000,
      input_tokens: 1, output_tokens: 1, account: null,
    } as unknown as SessionTokenUsage;
    const model = sessionUsageLabels(usage, null);
    if (model.state !== 'ok') throw new Error('fixture must be ok');
    expect(model.context.percentText).toBe(`${contextPercentSpoken(contextUsedPct(414600, 1000000))}%`);
    expect(model.context.percentText).toBe('41%');
  });
});
