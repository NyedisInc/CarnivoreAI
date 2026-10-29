import { describe, expect, test } from 'vitest';
import { resetAll, type BulkPreview } from './reset-all';
import type { RunningElsewhere } from './switch-model';

const rows: RunningElsewhere[] = [
  { session_id: 'one', tmux_session: 'cloude_one', label: 'one', status: 'working', provider: 'claude', account_id: 'old', active_account_id: 'new' },
  { session_id: 'two', tmux_session: 'cloude_two', label: 'two', status: 'working', provider: 'claude', account_id: 'old', active_account_id: 'new' },
];

const safe = (name: string): BulkPreview => ({
  name, pane_state: 'alive', projected: { kind: 'agent', actionable: true, conversation: 'resumed' },
});

describe('provider reset all', () => {
  test('restarts only the confirmed snapshot after a fresh account and resume check for each row', async () => {
    const calls: string[] = [];
    const outcome = await resetAll(rows, {
      running: async () => { calls.push('read'); return rows; },
      preview: async (name) => { calls.push(`preview:${name}`); return safe(name); },
      respawn: async (name) => { calls.push(`respawn:${name}`); return { ok: true }; },
    });
    expect(outcome).toEqual({ restarted: 2, failures: [] });
    expect(calls).toEqual(['read', 'preview:cloude_one', 'read', 'respawn:cloude_one', 'read', 'preview:cloude_two', 'read', 'respawn:cloude_two']);
  });

  test('refuses a fresh conversation and stops when the target changes during preview', async () => {
    let reads = 0;
    const posted: string[] = [];
    const outcome = await resetAll(rows, {
      running: async () => {
        reads += 1;
        return reads < 3 ? rows : rows.map((row) => ({ ...row, active_account_id: 'other' }));
      },
      preview: async (name) => name === 'cloude_one'
        ? { ...safe(name), projected: { ...safe(name).projected, conversation: 'none_recorded' } }
        : safe(name),
      respawn: async (name) => { posted.push(name); return { ok: true }; },
    });
    expect(posted).toEqual([]);
    expect(outcome.failures.map(({ reason }) => reason)).toEqual(['unsafe', 'changed']);
  });

  test('reports a failed session and continues with the next one', async () => {
    const outcome = await resetAll(rows, {
      running: async () => rows,
      preview: async (name) => safe(name),
      respawn: async (name) => name === 'cloude_one' ? { ok: false, detail: 'pane exited' } : { ok: true },
    });
    expect(outcome.restarted).toBe(1);
    expect(outcome.failures).toEqual([{ row: rows[0], reason: 'restart', detail: 'pane exited' }]);
  });
});
