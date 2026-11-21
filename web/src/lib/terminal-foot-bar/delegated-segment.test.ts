/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { delegatedSegment } from './delegated-segment';
import type { DelegatedUsage } from '../../opscenter/api/types';

const base: DelegatedUsage = { jobs: 2, input_tokens: 900, output_tokens: 300, cache_read_tokens: 1000, cache_write_tokens: 800, cost_usd: 0.4, accounts: ['work'] };

test('nothing delegated draws no segment, never a zero', () => {
  expect(delegatedSegment(null)).toBeNull();
  expect(delegatedSegment(undefined)).toBeNull();
  expect(delegatedSegment({ ...base, jobs: 0 })).toBeNull();
});

test('hover: title, then one bullet each for total and spend', () => {
  const s = delegatedSegment(base);
  expect(s?.title).toBe('work done on other computers:\n\u2022 total: 2 jobs, 3k tokens\n\u2022 cost $0.40, 900 tokens in, 300 tokens out');
  expect(s?.live).toBe(false);
});

test('running jobs add the active bullet and turn it live', () => {
  const s = delegatedSegment({ ...base, running: 1, running_on: ['tower'] });
  expect(s?.title).toContain('\u2022 active: 1 running on tower, tokens when done');
  expect(s?.live).toBe(true);
});

test('command-only history draws the icon, not green, and has no spend bullet', () => {
  const s = delegatedSegment({ ...base, jobs: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, remote_jobs: 12, ran_on: ['tower'] });
  expect(s?.live).toBe(false);
  expect(s?.title).toBe('work done on other computers:\n\u2022 total: 12 jobs, 0 tokens');
});
