/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
let reply: unknown = null;

vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetch: async (path: string) => {
    calls.push(path);
    return reply;
  },
}));

import TimerBadge from './TimerBadge.svelte';
import { closeTimerList, TIMER_LIST_ID } from './popup';
import { durationText, emptyMessage, orderRows, timerChip, untilText, type SessionTimers } from './timers';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
const NOW = Date.parse('2026-09-27T10:00:00Z');

beforeEach(() => {
  calls.length = 0;
  reply = null;
});

afterEach(async () => {
  closeTimerList();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  vi.useRealTimers();
});

function render(props: Record<string, unknown>): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TimerBadge, { target, props: props as never }));
  flushSync();
  return target;
}

function payload(over: Partial<SessionTimers> = {}): SessionTimers {
  return {
    state: 'ok', family: 'claude', conversation_uuid: 'u', process: 'alive',
    process_started_at: '2026-09-27T08:00:00Z',
    counts: { total: 3, live: 2, fired: 0, cancelled: 1, superseded: 0, expired: 0, lost: 0,
      refused: 0, unknown: 0, shape_unrecognized: 0 },
    next_fire_at: '2026-09-27T10:10:00Z',
    timers: [
      { id: 'ef56ab78', kind: 'cron', status: 'cancelled', cron: '*/30 * * * *', human_schedule: 'Every 30 minutes',
        delay_seconds: null, recurring: true, durable: false, created_at: '2026-09-27T09:01:00Z',
        fire_at: null, expires_at: null, prompt: 'old job', reason: null },
      { id: 'toolu_w1', kind: 'wakeup', status: 'live', cron: null, human_schedule: null,
        delay_seconds: 1800, recurring: null, durable: null, created_at: '2026-09-27T09:50:00Z',
        fire_at: '2026-09-27T10:20:00Z', expires_at: null, prompt: 'check the deploy', reason: 'waiting' },
      { id: '49759e95', kind: 'cron', status: 'live', cron: '*/5 * * * *', human_schedule: 'Every 5 minutes',
        delay_seconds: null, recurring: true, durable: false, created_at: '2026-09-27T09:00:00Z',
        fire_at: '2026-09-27T10:10:00Z', expires_at: '2026-10-04T09:00:00Z', prompt: 'poll', reason: null },
    ],
    background: { open: 2, detail: 'a floor', parked: [] },
    detail: '', as_of: null,
    ...over,
  };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

test('the countdown words', () => {
  expect(untilText('2026-09-27T10:18:00Z', NOW)).toBe('18m');
  expect(untilText('2026-09-27T10:00:30Z', NOW)).toBe('1m');
  expect(untilText('2026-09-27T13:30:00Z', NOW)).toBe('3h');
  expect(untilText('2026-09-29T10:00:00Z', NOW)).toBe('2d');
  expect(untilText('2026-09-27T09:59:00Z', NOW)).toBe('due');
  expect(untilText('not a time', NOW)).toBeNull();
  expect(untilText(null, NOW)).toBeNull();
  expect(durationText(1800)).toBe('30m');
});

test('no chip for a null, absent, zero or negative live count', () => {
  for (const live of [null, undefined, 0, -1, Number.NaN]) {
    expect(timerChip({ timers_live: live as never, timers_next_fire_at: '2026-09-27T10:18:00Z' }, NOW)).toBeNull();
    expect(render({ live, sessionId: 's' }).querySelector('.timer-chip')).toBeNull();
  }
  expect(render({ live: 1, sessionId: 's' }).querySelector('.timer-chip')).not.toBeNull();
});

test('the chip reads the next fire, or the count when no fire time is known', () => {
  expect(timerChip({ timers_live: 2, timers_next_fire_at: '2026-09-27T10:18:00Z' }, NOW)).toEqual({
    text: '18m', title: '2 live timers, next fires in 18m', live: 2,
  });
  expect(timerChip({ timers_live: 1, timers_next_fire_at: null }, NOW)).toEqual({
    text: '1 timer', title: '1 live timer', live: 1,
  });
});

test('the countdown moves on its own clock between polls', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  const root = render({ live: 1, nextFireAt: '2026-09-27T10:18:00Z', sessionId: 's' });
  expect(root.querySelector('button')!.textContent).toBe('18m');
  vi.setSystemTime(NOW + 5 * 60000);
  vi.advanceTimersByTime(30000);
  flushSync();
  expect(root.querySelector('button')!.textContent).toBe('13m');
});

test('a click opens the list, reads the route once, and does not reach the row', async () => {
  reply = payload();
  const row = document.createElement('div');
  const rowClicks = vi.fn();
  row.addEventListener('click', rowClicks);
  document.body.append(row);
  const target = document.createElement('div');
  row.append(target);
  mounted.push(mount(TimerBadge, { target, props: { live: 2, nextFireAt: '2026-09-27T10:10:00Z', sessionId: 'adopted:x y', name: 'api work' } }));
  flushSync();
  target.querySelector('button')!.click();
  await settle();
  expect(rowClicks).not.toHaveBeenCalled();
  expect(calls).toEqual(['/sessions/adopted%3Ax%20y/timers']);
  const dialog = document.getElementById(TIMER_LIST_ID)!.querySelector('[role="dialog"]')!;
  expect(dialog.getAttribute('aria-label')).toBe('timers of api work');
  const statuses = [...dialog.querySelectorAll('tbody tr')].map((tr) => tr.getAttribute('data-timer-status'));
  expect(statuses).toEqual(['live', 'live', 'cancelled']);
  expect(dialog.textContent).toContain('2 live · 1 ended · 0 unknown');
  expect(dialog.textContent).toContain('Every 5 minutes');
  expect(dialog.textContent).toContain('once, after 30m');
  expect(dialog.textContent).toContain('canceled');
  expect(dialog.querySelector('[data-timers-background]')!.textContent).toContain('2 background shells or monitors open');
});

test('not applicable and not measured are said in words, never as an empty table', () => {
  expect(emptyMessage(payload({ state: 'not_applicable', counts: null, timers: [] }))).toBe('this agent records no timers');
  expect(emptyMessage(payload({ state: 'unchecked', counts: null }))).toBe('whether these timers are live could not be measured');
  expect(emptyMessage(payload({ timers: [] }))).toBe('this conversation has set no timers');
  expect(emptyMessage(payload())).toBeNull();
});

test('live timers sort first, soonest first', () => {
  expect(orderRows(payload().timers).map((row) => row.id)).toEqual(['49759e95', 'toolu_w1', 'ef56ab78']);
});
