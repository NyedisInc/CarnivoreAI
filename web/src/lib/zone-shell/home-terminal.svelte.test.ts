/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

const state = vi.hoisted(() => ({
  sessions: { data: [] as unknown[], status: 'ok', refresh: async () => {} },
  asleep: { data: [] as unknown[], status: 'ok', refresh: async () => {} },
}));
vi.mock('../../opscenter/api', () => ({ sessions: state.sessions, asleep: state.asleep }));
vi.mock('../launchpad/create-host', () => ({ browserCreateHost: () => ({}) }));
const flow = vi.hoisted(() => ({ calls: [] as unknown[][], next: 20 }));
vi.mock('../launchpad/create-flow', () => ({
  createConsoleFlow: vi.fn(async (...args: unknown[]) => {
    flow.calls.push(args);
    const id = flow.next++;
    state.sessions.data = [...state.sessions.data, shellRow(id)];
    return { outcome: 'created', session: { id: `ses_${id}` }, payload: {} };
  }),
}));

import { pickHomeShell, targetGone, useHomeTerminal, type HomeTerminal } from './home-terminal.svelte';

function shellRow(id: number, tmux = 'carnivore_home-terminal'): unknown {
  return { session_row_id: id, agent_family: 'shell', tmux_session: id === 20 ? tmux : `${tmux}-${id}`, session: { id: `ses_${id}` } };
}
const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) { await Promise.resolve(); flushSync(); } };
const roots: Array<() => void> = [];
function place(target: string | null, claimKey: string): HomeTerminal {
  let home!: HomeTerminal;
  roots.push($effect.root(() => { home = useHomeTerminal(() => ({ active: true, target, claimKey })); }));
  return home;
}

beforeEach(() => { state.sessions.data = []; state.asleep.data = []; flow.calls.length = 0; flow.next = 20; });
afterEach(() => { while (roots.length) roots.pop()!(); });

describe('targetGone', () => {
  test('no target, an unlisted row and an unlisted app id are gone; a live or asleep row is not', () => {
    const live = [{ session_row_id: 7, session: { id: 'ses_7' } }] as never;
    expect(targetGone(null, live, [])).toBe(true);
    expect(targetGone('row:9', live, [])).toBe(true);
    expect(targetGone('ses_missing', live, [])).toBe(true);
    expect(targetGone('row:7', live, [])).toBe(false);
    expect(targetGone('ses_7', live, [])).toBe(false);
    expect(targetGone('row:9', live, [{ id: 9, asleep: true }] as never)).toBe(false);
  });
});

describe('pickHomeShell', () => {
  test('takes the lowest home shell nobody holds, ignores other shells and agents', () => {
    const rows = [shellRow(20), shellRow(21), { session_row_id: 5, agent_family: 'shell', tmux_session: 'carnivore_console-x' }] as never;
    expect(pickHomeShell(rows, new Set())).toBe(20);
    expect(pickHomeShell(rows, new Set([20]))).toBe(21);
    expect(pickHomeShell(rows, new Set([20, 21]))).toBeNull();
  });
});

describe('useHomeTerminal', () => {
  test('a gone target creates one quiet home shell and binds it; reopening binds the same one', async () => {
    const first = place('row:99', 'core.terminal');
    await settle();
    expect(flow.calls).toHaveLength(1);
    expect(flow.calls[0]!.slice(2)).toEqual(['~', { sessionName: 'home-terminal', quiet: true }]);
    expect(first.target).toBe('row:20');
    roots.pop()!();
    const again = place(null, 'core.terminal');
    await settle();
    expect(flow.calls).toHaveLength(1);
    expect(again.target).toBe('row:20');
  });

  test('two placements never share a shell', async () => {
    const a = place(null, 'core.terminal@a');
    const b = place(null, 'core.terminal@b');
    await settle();
    expect(new Set([a.target, b.target]).size).toBe(2);
    expect(flow.calls).toHaveLength(2);
  });

  test('a live or asleep target creates nothing and keeps its own target', async () => {
    state.sessions.data = [{ session_row_id: 7, session: { id: 'ses_7' } }];
    state.asleep.data = [{ id: 8, asleep: true }];
    const live = place('row:7', 'k1');
    const sleeping = place('row:8', 'k2');
    await settle();
    expect(flow.calls).toHaveLength(0);
    expect([live.target, sleeping.target, live.pending, sleeping.pending]).toEqual(['row:7', 'row:8', false, false]);
  });
});
