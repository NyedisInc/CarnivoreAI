/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(), listTargets: vi.fn(), getRunCounts: vi.fn(), listRuns: vi.fn(), listProjectChoices: vi.fn(), listSessionRecords: vi.fn(),
  getRun: vi.fn(), listFeed: vi.fn(),
}));
vi.mock('../api', () => stub);
vi.mock('../../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import ReviewTab from './ReviewTab.svelte';
import { feed } from '../feed-store.svelte';
import { data } from '../page-store.svelte';
import { unread } from '../read-state.svelte';

const NOW = Math.floor(Date.now() / 1000);
const mk = (id: string, over: Record<string, unknown> = {}) => ({
  run_id: id, automation_id: 'aut_a', automation_name: 'alpha', number: 1, trigger: 'schedule', slot_at: NOW - 300, started_at: NOW - 300, ended_at: NOW - 298,
  status: 'succeeded', reason: null, skip_count: null, error: null, has_report: false, report_bytes: null, host: null, output_empty: false, usage: null,
  delivered: null, attachments: null, cost_usd: null, title: null, summary: null, ...over,
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

beforeEach(async () => {
  vi.clearAllMocks();
  stub.listFeed.mockResolvedValue({ runs: [], total: 0, next_before: null });
  data.status = 'ready';
  data.tz = 'UTC';
  data.now = NOW;
  data.pressed = {};
  data.drawer = null;
  data.automations = [];
  unread.seenAt = null;
  unread.read = [];
  feed.runs = [mk('r1', { title: 'checked 12 disks', summary: 'all healthy.' }), mk('r2')] as never;
  feed.total = 2;
  feed.nextBefore = null;
  feed.status = 'ready';
  app = mount(ReviewTab, { target: document.body });
  await settle();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('looks good marks the run read once and the to review count drops by one', async () => {
  expect(q('[data-review-counts]').textContent).toBe('2 to review, 2 runs');
  q<HTMLButtonElement>('[data-good="r1"]').click();
  await settle();
  expect(unread.read).toEqual(['r1']);
  expect(q('[data-review-counts]').textContent).toBe('1 to review, 2 runs');
  expect(document.querySelector('.f-row[data-run="r1"]')).toBeNull();
  q<HTMLButtonElement>('[data-mode="all"]').click();
  await settle();
  expect(q('.f-row[data-run="r1"] .f-act').textContent).toContain('reviewed');
  expect(document.querySelector('[data-good="r1"]')).toBeNull();
});

test('a row shows the stored title and summary; a null title shows the feed face and no summary line', () => {
  expect(q('.f-row[data-run="r1"] .f-body [data-run-title]').textContent).toBe('checked 12 disks');
  expect(q('.f-row[data-run="r1"] .f-sum').textContent).toBe('all healthy.');
  expect(q('.f-row[data-run="r2"] .f-body [data-run-title]').textContent?.trim().length).toBeGreaterThan(0);
  expect(document.querySelector('.f-row[data-run="r2"] .f-sum')).toBeNull();
});

test('a click on a row opens the run in the drawer; mark all reviewed empties the list', async () => {
  q('.f-row[data-run="r2"] .f-body').click();
  expect(data.drawer).toEqual({ kind: 'run', id: 'r2' });
  q<HTMLButtonElement>('[data-markall]').click();
  await settle();
  expect(unread.seenAt).not.toBeNull();
  expect(q('[data-review-empty]').getAttribute('data-review-empty')).toBe('caught');
});

test('a pressed tile shows its note and clearing it reads the feed again', async () => {
  data.pressed = { failed_24h: true };
  await settle();
  expect(q('[data-review-filter]').textContent).toContain('runs that failed in the last 24 hours');
  q<HTMLButtonElement>('[data-clearfilter]').click();
  await settle();
  expect(data.pressed).toEqual({});
  expect(stub.listFeed).toHaveBeenCalled();
});
