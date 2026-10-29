import { describe, expect, test } from 'vitest';
import { sortAccounts } from '../ledger/ledger-model';
import type { AccountSwitchState } from './switch-model';
import type { LedgerAccount } from '../ledger/ledger-model';

const acct = (id: string, provider: string, name: string) =>
  ({ id, provider, name }) as unknown as LedgerAccount;

const state = {
  auto_switch: true,
  threshold_percent: 90,
  last_switch: null,
  restarts_running_sessions: false,
  active: [
    { provider: 'claude', account_id: 'c-b', source: 'pointer', pointer: 'c-b', next_order: ['c-d', 'c-a'] },
    { provider: 'codex', account_id: 'x-z', source: 'pointer', pointer: 'x-z', next_order: [] },
  ],
} as AccountSwitchState;

describe('providers order', () => {
  test('providers alphabetical, active first, then switch order, unpickable last by name', () => {
    const rows = [
      acct('x-y', 'codex', 'Y'),
      acct('c-a', 'claude', 'A'),
      acct('c-e', 'claude', 'E'),
      acct('c-b', 'claude', 'B'),
      acct('x-z', 'codex', 'Z'),
      acct('c-d', 'claude', 'D'),
      acct('c-c', 'claude', 'C'),
    ];
    expect(sortAccounts(rows, state).map((r) => r.id)).toEqual([
      'c-b', 'c-d', 'c-a', 'c-c', 'c-e', 'x-z', 'x-y',
    ]);
  });

  test('without the switch state it keeps the old provider then name order', () => {
    const rows = [acct('2', 'claude', 'B'), acct('1', 'claude', 'A')];
    expect(sortAccounts(rows).map((r) => r.id)).toEqual(['1', '2']);
  });
});
