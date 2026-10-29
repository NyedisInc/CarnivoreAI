import { expect, test } from 'vitest';
import type { Automation, RunCounts } from '../api';
import { capped, cardTag, cardWord, columns, FIND_AFTER, GROUP_CAP, isOften, showFind, tileValues } from './overview-model';

const NOW = 1_800_000_000;
const run = (n: number, status: string, reason: string | null = null, at = NOW - 600) => ({
  run_id: `r${n}`, number: n, status, reason, trigger: 'schedule', attempt: null, slot_at: at, started_at: at, ended_at: at + 2, skip_count: null, report_bytes: 1, output_empty: false,
});
const auto = (id: string, cron: string, recent: ReturnType<typeof run>[] = [], over: Partial<Automation> = {}): Automation =>
  ({ automation_id: id, name: id, enabled: true, trigger: { cron, timezone: 'local' }, target: { kind: 'command' }, next_fire_at: null, revision: 1, recent, ...over }) as unknown as Automation;
const counts = (waiting: number, failed: number): RunCounts => ({
  now: NOW, hosts: [], has_unrecorded_host: false, next_change_at: null,
  counters: Object.fromEntries(
    ['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you'].map((id) => [
      id, { count: id === 'waiting_on_you' ? waiting : id === 'failed_24h' ? failed : 0, automation_ids: [] },
    ]),
  ) as unknown as RunCounts['counters'],
});
const fresh = { seenAt: null, read: new Set<string>() };

test('cadence buckets: hourly or more often versus daily, weekly and unparseable', () => {
  expect(isOften('*/15 * * * *')).toBe(true);
  expect(isOften('0 * * * *')).toBe(true);
  expect(isOften('0 */1 * * *')).toBe(true);
  expect(isOften('0 */2 * * *')).toBe(false);
  expect(isOften('30 7 * * 1-5')).toBe(false);
  expect(isOften('0 9 * * 1')).toBe(false);
  expect(isOften('nonsense')).toBe(false);
  expect(isOften('')).toBe(false);
  const c = columns([auto('a', '*/5 * * * *'), auto('b', '0 9 * * *'), auto('c', 'bad')]);
  expect(c.often.map((a) => a.automation_id)).toEqual(['a']);
  expect(c.slow.map((a) => a.automation_id)).toEqual(['b', 'c']);
});

test('tiles: active, soonest next run, needs you, failed', () => {
  const rows = [
    auto('a', '*/5 * * * *', [run(1, 'failed')], { next_fire_at: NOW + 900 }),
    auto('b', '0 9 * * *', [run(1, 'succeeded')], { next_fire_at: NOW + 300 }),
    auto('c', '0 9 * * *', [run(1, 'waiting_on_you')], { enabled: false, next_fire_at: NOW + 60 }),
  ];
  const v = tileValues(rows, counts(0, 4), fresh, NOW);
  expect(v).toMatchObject({ active: 2, total: 3, next: { name: 'b', at: NOW + 300 }, needs: 2, failed: 4 });
  expect(tileValues(rows, counts(5, 0), fresh, NOW).needs).toBe(5);
  expect(tileValues(rows, null, { seenAt: null, read: new Set(['r1']) }, NOW).needs).toBe(0);
});

test('tiles with nothing: zeros, no next run, no counters', () => {
  expect(tileValues([], null, fresh, NOW)).toEqual({ active: 0, total: 0, next: null, needs: 0, failed: 0 });
  expect(tileValues([auto('a', '0 9 * * *', [], { enabled: false })], counts(0, 0), fresh, NOW).next).toBeNull();
});

test('the attention tag and the status word', () => {
  const failed = auto('f', '0 9 * * *', [run(2, 'failed')]);
  expect(cardTag(failed, true, false, fresh, NOW)).toEqual({ key: 'last_failed', n: 0, tone: 'coral' });
  expect(cardTag(auto('w', '0 9 * * *', [run(1, 'waiting_on_you')]), true, false, fresh, NOW)?.key).toBe('needs_you');
  expect(cardTag(auto('s', '0 9 * * *', [run(1, 'skipped', 'overlap')]), true, false, fresh, NOW)).toEqual({ key: 'skipped', n: 0, tone: 'gray' });
  expect(cardTag(auto('p', '0 9 * * *', [run(1, 'skipped', 'scheduler_paused')]), true, false, fresh, NOW)).toBeNull();
  expect(cardTag(auto('m', '0 9 * * *', [run(3, 'failed'), run(2, 'failed')]), true, false, fresh, NOW)).toEqual({ key: 'need_you', n: 2, tone: 'yellow' });
  expect(cardTag(failed, false, false, fresh, NOW)).toBeNull();
  expect(cardTag(failed, true, true, fresh, NOW)).toBeNull();
  expect(cardWord(failed, true, false)).toEqual({ key: 'failed', tone: 'coral' });
  expect(cardWord(auto('r', '0 9 * * *', [run(1, 'running')]), true, false)?.key).toBe('running');
  expect(cardWord(failed, false, false)?.key).toBe('off');
  expect(cardWord(failed, true, true)?.key).toBe('paused');
  expect(cardWord(auto('ok', '0 9 * * *', [run(1, 'succeeded')]), true, false)).toBeNull();
  expect(cardWord(auto('new', '0 9 * * *', []), true, false)).toBeNull();
});

test('a column caps at 12 and shows all on request; the find box is past 20', () => {
  const rows = Array.from({ length: 15 }, (_, i) => i);
  expect(GROUP_CAP).toBe(12);
  expect(capped(rows, false)).toHaveLength(12);
  expect(capped(rows, true)).toHaveLength(15);
  expect(capped([1, 2], false)).toHaveLength(2);
  expect(FIND_AFTER).toBe(20);
  expect(showFind(20)).toBe(false);
  expect(showFind(21)).toBe(true);
});
