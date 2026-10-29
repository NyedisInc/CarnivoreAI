import { expect, test } from 'vitest';
import { footAccount } from './foot-account';

const rows = [
  { id: 'a', name: 'Work account', short_name: 'work' },
  { id: 'b', name: 'Personal', short_name: null },
];
const active = [{ provider: 'claude', account_id: 'a' }, { provider: 'codex', account_id: null }];

test('the active account shows its short name, no warning', () => {
  expect(footAccount('claude', 'a', rows, active)).toEqual({ name: 'work', mismatch: false });
});

test('a session on another account than the active one warns', () => {
  expect(footAccount('claude', 'b', rows, active)).toEqual({ name: 'Personal', mismatch: true });
});

test('not measured, or not in the ledger, draws nothing', () => {
  expect(footAccount('claude', null, rows, active)).toBeNull();
  expect(footAccount('claude', 'zz', rows, active)).toBeNull();
  expect(footAccount('claude', 'a', undefined, active)).toBeNull();
});

test('an unknown active account never raises the warning', () => {
  expect(footAccount('codex', 'b', rows, active)).toEqual({ name: 'Personal', mismatch: false });
  expect(footAccount('claude', 'b', rows, undefined)?.mismatch).toBe(false);
});
