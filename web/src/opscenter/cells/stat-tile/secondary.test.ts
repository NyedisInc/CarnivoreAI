/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { stats, type Figure, type Figures } from '../../data/stats';
import { secondary } from './series';
import { STAT_TILE_META } from '../../engine/stat-tile-meta';
import { pickState } from '../../lib/states';

const ok = (value: number): Figure => ({ value, status: 'ok', message: '' });
const none: Figure = { value: null, status: 'loading', message: '' };
const card = (id: string) => stats.find((entry) => entry.id === id)!;

function figures(over: Partial<Figures> = {}): Figures {
  return {
    running: ok(2), sessions24h: ok(9), projects: ok(62), ledger: ok(49), alive: ok(7),
    subagentsRunning: ok(1), total: 9, skills: ok(0), ledgerResetSeconds: 5 * 3600 + 9 * 60,
    detail: { liveRows: 9, closed24h: 0, projectsWithLive: 4, subagentParents: 1 },
    ...over,
  };
}

describe('stat tile secondary', () => {
  test('each tile reads its own real second number', () => {
    const f = figures();
    expect(secondary(card('running'), f)).toEqual({ text: 'of 7 alive', meter: null });
    expect(secondary(card('sessions'), f)?.text).toBe('9 live, 0 closed');
    expect(secondary(card('projects'), f)?.text).toBe('4 with live sessions');
    expect(secondary(card('ledger'), f)).toEqual({ text: 'resets in 5h 09m', meter: 49 });
    expect(secondary(card('alive'), f)).toEqual({ text: '2 stopped', meter: 78 });
    expect(secondary(card('subagents'), f)?.text).toBe('in 1 session');
  });

  test('an unmeasured figure draws no secondary, never a zero', () => {
    const f = figures({ alive: none, ledger: none, detail: { liveRows: null, closed24h: null, projectsWithLive: null, subagentParents: null } });
    for (const id of ['running', 'sessions', 'projects', 'ledger', 'alive', 'subagents']) expect(secondary(card(id), f)).toBeNull();
  });
});

describe('stat tile height states', () => {
  test('a short tile collapses to the line state', () => {
    const states = STAT_TILE_META['stat-running'].heightStates;
    expect(pickState(states, 69, '')).toBe('flat');
    expect(pickState(states, 56, 'flat')).toBe('line');
    expect(pickState(states, 56, '')).toBe('line');
    expect(pickState(states, 120, '')).toBe('graph');
  });
});
