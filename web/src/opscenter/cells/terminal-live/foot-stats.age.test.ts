import { expect, test } from 'vitest';
import { statsGroups } from './foot-stats';
import { sessionUsageLabels } from '../../api';
import type { SessionTokenUsage } from '../../api';

const usage = {
  state: 'ok', model: 'claude-opus-5', input_tokens: 1, output_tokens: 1, cost_estimate_usd: 1,
  context_remaining_pct: 50, context_used_tokens: 1, context_window_tokens: 2, account: null,
} as unknown as SessionTokenUsage;

const cells = (createdAt: string | null) =>
  statsGroups(sessionUsageLabels(usage, null), usage, Date.parse('2026-11-03T11:05:00Z'), createdAt).flat();

test('a readable start draws the age after cost, in the shared elapsed form', () => {
  const keys = cells('2026-11-03T10:00:00Z').map((c) => c.key);
  expect(keys.indexOf('age')).toBe(keys.indexOf('cost') + 1);
  const age = cells('2026-11-03T10:00:00Z').find((c) => c.key === 'age');
  expect(age && age.kind === 'text' ? age.row.text : null).toBe('1h 05m');
});

test('an unknown start leaves the cell out, never zero', () => {
  expect(cells(null).some((c) => c.key === 'age')).toBe(false);
  expect(cells('not a date').some((c) => c.key === 'age')).toBe(false);
});
