import { describe, expect, test } from 'vitest';
import { provisionalUsage } from './provisional-usage';
import type { LedgerSnapshot, SessionInfo } from '../../api/types';

const LEDGER: LedgerSnapshot = {
  accounts: [
    {
      id: 'acct_main',
      name: 'Main',
      short_name: 'Main',
      provider: 'claude',
      plan: 'max',
      identity: 'a@example.com',
      credential_state: 'ok',
      fetched_at: '2026-11-22T00:00:00Z',
      next_poll_at: null,
      error: null,
      windows: [{ kind: 'five_hour', label: '5h', used_pct: 40, resets_at: null }],
      color: null,
      managed: true,
    },
  ],
  total: { accounts: 1, windows: [] },
  loop: { alive: true, last_pass_at: null },
};

describe('provisionalUsage', () => {
  test('hydrates model, effort, context headroom, and ledger windows at 0ms from pushed row', () => {
    const row = {
      session: { id: 'ses_1' },
      agent_family: 'claude',
      account_id: 'acct_main',
      running_model: 'claude-opus-4-6',
      running_model_effort: 'high',
      running_model_tier: 5,
      running_context_used_pct: 32,
    } as unknown as SessionInfo;

    const out = provisionalUsage(row, LEDGER);
    expect(out).not.toBeNull();
    expect(out?.state).toBe('ok');
    expect(out?.model).toBe('claude-opus-4-6');
    expect(out?.effort).toBe('high');
    expect(out?.context_remaining_pct).toBe(68);
    expect(out?.account?.id).toBe('acct_main');
    expect(out?.account?.windows).toHaveLength(1);
  });

  test('returns null for shells or rows with no measured facts yet', () => {
    expect(provisionalUsage({ agent_family: 'shell' } as SessionInfo, LEDGER)).toBeNull();
    expect(provisionalUsage({ agent_family: 'claude' } as SessionInfo, null)).toBeNull();
    expect(provisionalUsage(null, LEDGER)).toBeNull();
  });
});
