import { expect, test } from 'vitest';
import { clockFor } from '../logic/words';
import type { FeedRun } from '../logic/types';
import { isUnread } from '../logic/feed';
import { markAllRead, unread } from '../read-state.svelte';
import { reviewKeyAction } from './review-keys';
import { dayGroups, listed, modeForPressed, needsYou, runLines, runWord, toReviewCount } from './review-model';

const NOW = 1_800_000_000;
const clock = clockFor('UTC');
const run = (id: string, at: number, over: Partial<FeedRun> = {}): FeedRun =>
  ({
    run_id: id, automation_id: 'aut_a', automation_name: 'alpha', number: 1, trigger: 'schedule', slot_at: at, started_at: at, ended_at: at + 2, status: 'succeeded',
    reason: null, skip_count: null, error: null, has_report: true, report_bytes: 1, host: null, output_empty: false, usage: null, delivered: null, attachments: null, cost_usd: null,
    ...over,
  }) as FeedRun;

test('days group by the computer clock and read today, yesterday, then a weekday date', () => {
  const runs = [run('a', NOW - 60), run('b', NOW - 120), run('c', NOW - 86400), run('d', NOW - 5 * 86400)];
  const days = dayGroups(runs, clock, NOW);
  expect(days.map((d) => d.runs.length)).toEqual([2, 1, 1]);
  expect(days[0]!.label).toBe('today');
  expect(days[1]!.label).toBe('yesterday');
  expect(days[2]!.label).toMatch(/^[A-Z][a-z]{2} \d+$/);
});

test('days stay unique when runs arrive out of time order (a run ended on the next day of its slot)', () => {
  const runs = [run('a', NOW - 60), run('c', NOW - 86400), run('b', NOW - 120, { ended_at: NOW - 86400 + 5 }), run('d', NOW - 130)];
  const days = dayGroups(runs, clock, NOW);
  expect(new Set(days.map((d) => d.key)).size).toBe(days.length);
  expect(days.flatMap((d) => d.runs).map((r) => r.run_id).sort()).toEqual(['a', 'b', 'c', 'd']);
});

test('to review is exactly the B9 unread rule; all lists every run; mark all moves seen-at past every run', () => {
  const runs = [run('a', NOW - 60), run('b', NOW - 3600), run('c', NOW - 7200)];
  const state = { seenAt: null as string | null, read: new Set(['b']) };
  expect(listed(runs, 'review', state, NOW).map((r) => r.run_id)).toEqual(['a', 'c']);
  expect(listed(runs, 'review', state, NOW).every((r) => isUnread(r, state, NOW))).toBe(true);
  expect(listed(runs, 'all', state, NOW)).toHaveLength(3);
  expect(toReviewCount(runs, state, NOW)).toBe(2);
  expect(unread.seenAt).toBeNull();
  markAllRead(new Date((NOW + 5) * 1000));
  const after = { seenAt: unread.seenAt, read: new Set(unread.read) };
  expect(unread.seenAt).toBe(new Date((NOW + 5) * 1000).toISOString());
  expect(toReviewCount(runs, after, NOW + 5)).toBe(0);
});

test('status word and tone: done, needs you, failed, skipped, running, paused', () => {
  expect(runWord({ status: 'succeeded', reason: null })).toEqual({ key: 'done', tone: 'calm' });
  expect(runWord({ status: 'waiting_on_you', reason: null })).toEqual({ key: 'needs_you', tone: 'yellow' });
  expect(runWord({ status: 'failed', reason: 'exit_2' })).toEqual({ key: 'failed', tone: 'coral' });
  expect(runWord({ status: 'skipped', reason: 'overlap' })).toEqual({ key: 'skipped', tone: 'yellow' });
  expect(runWord({ status: 'skipped', reason: 'scheduler_paused' })).toEqual({ key: 'paused', tone: 'calm' });
  expect(runWord({ status: 'claimed', reason: null }).key).toBe('running');
  expect(needsYou({ status: 'skipped', reason: 'scheduler_paused' })).toBe(false);
  expect(needsYou({ status: 'failed', reason: null })).toBe(true);
});

test('a null title falls back to the feed face and shows no summary line; a stored title and summary are shown as written', () => {
  expect(runLines({ title: null, summary: null }, 'heartbeat ok')).toEqual({ title: 'heartbeat ok', summary: '' });
  expect(runLines({}, 'heartbeat ok')).toEqual({ title: 'heartbeat ok', summary: '' });
  expect(runLines({ title: 'checked 12 disks', summary: 'all healthy.' }, 'ignored')).toEqual({ title: 'checked 12 disks', summary: 'all healthy.' });
  expect(runLines({ title: 'ran', summary: null }, 'x')).toEqual({ title: 'ran', summary: '' });
});

test('a pressed tile picks its mode and the keys map', () => {
  expect(modeForPressed({ waiting_on_you: true })).toBe('review');
  expect(modeForPressed({ failed_24h: true })).toBe('all');
  expect(modeForPressed({})).toBeNull();
  expect(reviewKeyAction({ key: 'j' }, false)).toBe('next');
  expect(reviewKeyAction({ key: 'k' }, false)).toBe('prev');
  expect(reviewKeyAction({ key: 'Enter' }, false)).toBe('open');
  expect(reviewKeyAction({ key: 'Enter' }, true)).toBeNull();
  expect(reviewKeyAction({ key: 'r' }, false)).toBe('good');
  expect(reviewKeyAction({ key: 'r', metaKey: true }, false)).toBeNull();
});
