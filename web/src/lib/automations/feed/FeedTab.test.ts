/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { createRequire } from 'node:module';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(),
  listTargets: vi.fn(),
  getRunCounts: vi.fn(),
  listRuns: vi.fn(),
  listFeed: vi.fn(),
  listChanges: vi.fn(),
  listProjectChoices: vi.fn(),
  listSessionRecords: vi.fn(),
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  continueRun: vi.fn(),
  fixFinding: vi.fn(),
  runAutomationNow: vi.fn(),
}));
vi.mock('../api', () => stub);
vi.mock('../../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));
vi.mock('../../blueprints/api', () => ({ listBlueprints: vi.fn().mockResolvedValue({ status: 'ok', blueprints: [] }) }));
vi.mock('../../../opscenter/api/host', () => ({ openSession: vi.fn(() => true), openSessions: vi.fn(() => true) }));

import FeedTab from './FeedTab.svelte';
import { data, setFilters, takeAddress, togglePressed } from '../page-store.svelte';
import { boundary, feed, loadFeed, reports } from '../feed-store.svelte';
import { unread } from '../read-state.svelte';
import { fv } from './feed-state.svelte';

const NOW = 1_800_000_000;
const run = (id: string, n: number, over: Record<string, unknown> = {}) => ({
  run_id: id, automation_id: 'aut_a', automation_name: 'alpha', number: n, status: 'succeeded', reason: null, trigger: 'schedule', attempt: null,
  slot_at: NOW - 600 * (9 - n), started_at: NOW - 600 * (9 - n), ended_at: NOW - 600 * (9 - n) + 2, skip_count: null, first_slot_at: null, last_slot_at: null,
  report_bytes: 40, output_empty: false, has_report: true, error: null, cost_usd: null, host: 'studio', usage: null, delivered: null,
  attachments: null, sessions: [], report: { summary: 'same' }, ...over,
});
const automation = (over: Record<string, unknown> = {}) => ({
  automation_id: 'aut_a', name: 'alpha', enabled: true, trigger: { cron: '0 7 * * 1', timezone: 'UTC' }, delivery: { notify: true, notify_on: null },
  revision: 1, last_run: null, next_fire_at: NOW + 600, description: '', project_id: null, misfire: 'run_once', retry_max: 0, retry_backoff_s: 300,
  max_runtime_s: null, median_took_s: 2, newest_output_empty: false, run_count: 5, newest_number: 5, spends: false, recent: [],
  files_under: { session_uuid: 'ses-1', project_id: 7 }, target: { kind: 'command', command: '/usr/bin/git pull', project_id: null },
  created_at: NOW - 9000, updated_at: NOW - 100, created_actor: { kind: 'app' }, updated_actor: { kind: 'app' }, ...over,
});
const targets = { kinds: ['command'], commands: ['/usr/bin/git pull'], recipes: [] };

const FOLD_FEED = [
  run('r5', 5, { report: { summary: 'c' } }),
  run('r4', 4, { report: { summary: 'c' } }),
  run('r3', 3, { report: { summary: 'c' } }),
  run('r2', 2, { report: { summary: 'b' } }),
  run('r1', 1, { report: { summary: 'a' } }),
];

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const all = (sel: string) => [...document.querySelectorAll<HTMLElement>(sel)];
const key = async (k: string) => {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  await settle();
};
const mountFeed = async (runs: unknown[], over: Record<string, unknown> = {}) => {
  stub.listFeed.mockResolvedValue({ runs, total: runs.length, next_before: null, ...over });
  data.automations = [automation()] as never;
  data.projects = [{ id: 7, name: 'proj' }] as never;
  data.sessions = [{ session_uuid: 'ses-1', label: 'build box' }] as never;
  data.tab = 'sessions';
  await loadFeed({});
  app = mount(FeedTab, { target: document.body });
  await settle();
};

type Call = { path: string; opts?: { method?: string; body?: { changes: Record<string, unknown>; expected_revision: number } } };
let calls: Call[] = [];

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.setSystemTime(new Date((NOW + 60) * 1000));
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.listChanges.mockResolvedValue({ changes: [] });
  stub.listAutomations.mockResolvedValue({ automations: [automation()], scheduler: { paused: false }, tz: 'UTC' });
  stub.listTargets.mockResolvedValue(targets);
  stub.getRunCounts.mockRejectedValue(new Error('no route'));
  stub.listProjectChoices.mockResolvedValue([]);
  stub.listSessionRecords.mockResolvedValue([]);
  stub.getRun.mockReturnValue(new Promise(() => {}));
  Object.assign(data, {
    status: 'ready', error: '', tz: 'UTC', now: NOW, paused: false, counts: null, targets, projects: [], sessions: [], selectedId: null, tab: 'sessions',
    paneOpen: false, paneTab: 'output', paneRunId: null, paneMode: null, seed: null, notice: '', where: '', feedRunId: null,
    filters: { automation: '', status: '', trigger: '', host: '' }, pressed: {},
  });
  Object.assign(feed, { runs: [], total: 0, nextBefore: null, status: 'idle', error: '', loadingMore: false });
  for (const k of Object.keys(reports)) delete reports[k];
  for (const k of Object.keys(boundary)) delete boundary[k];
  Object.assign(fv, { q: '', changedOnly: false, unreadOnly: false, filtersOpen: false, expanded: {}, sheet: false });
  unread.seenAt = null;
  unread.read = [];
  history.replaceState(null, '', '#automations/sessions');

  const require = createRequire(import.meta.url);
  delete (globalThis as Record<string, unknown>).Preferences;
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  for (const file of ['preferences.js', 'preference-bridge.js']) {
    const path = require.resolve(`../../../../../client/js/${file}`);
    delete require.cache[path];
    require(path);
  }
  calls = [];
  (globalThis as Record<string, unknown>).API = {
    call: async (path: string, opts?: Call['opts']) => {
      calls.push({ path, opts });
      return opts?.method === 'PATCH' ? { revision: 4, values: opts.body!.changes } : { revision: 3, values: {} };
    },
  };
  await (globalThis as unknown as { Preferences: { hydrate(): Promise<string> } }).Preferences.hydrate();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

test('identical runs fold, with the run that changed just below', async () => {
  await mountFeed(FOLD_FEED);
  const folds = all('[data-kind="fold"]');
  expect(folds).toHaveLength(1);
  expect(folds[0]!.dataset.run).toBe('r5');
  expect(folds[0]!.textContent).toContain('2 runs');
  const order = all('[data-run]').map((el) => el.dataset.run);
  expect(order.indexOf('r3')).toBe(order.indexOf('r5') + 1);
  expect(q('[data-run="r3"]').hasAttribute('data-chg')).toBe(true);
  expect(q('[data-feed-meta]').textContent).toContain('3 changed');
});

test('a row with a pending report never folds and is not counted changed', async () => {
  const pending = run('p2', 2, { report: undefined, report_omitted: true });
  delete (pending as Record<string, unknown>).report;
  await mountFeed([run('p3', 3, { report: { summary: 'x' } }), pending, run('p1', 1, { report: { summary: 'x' } })]);
  expect(q('[data-run="p2"]').dataset.kind).toBe('run');
  expect(q('[data-run="p2"]').hasAttribute('data-chg')).toBe(false);
  expect(all('[data-kind="fold"]')).toHaveLength(0);
});

test('mark all read and opening runs issue one debounced preferences write with the held revision', async () => {
  await mountFeed(FOLD_FEED);
  q('[data-act="mark-read"]').click();
  await settle();
  q('[data-run="r2"]').click();
  await settle();
  expect(calls.filter((c) => c.opts?.method === 'PATCH')).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(1100);
  await settle();
  const writes = calls.filter((c) => c.opts?.method === 'PATCH');
  expect(writes).toHaveLength(1);
  expect(writes[0]!.opts!.body!.expected_revision).toBe(3);
  expect(Object.keys(writes[0]!.opts!.body!.changes)).toContain('automation_runs_seen_at');
  expect(q('[data-feed-meta]').textContent).toContain('0 unread');
});

test('n walks the unread runs and wraps to the top with its notice', async () => {
  await mountFeed(FOLD_FEED);
  expect(data.feedRunId).toBe('r3');
  await key('n');
  expect(data.feedRunId).toBe('r2');
  await key('n');
  expect(data.feedRunId).toBe('r1');
  await key('n');
  expect(data.feedRunId).toBe('r5');
  expect(data.notice).toBe('back at the top of the unread');
});

test('the session fragment sets the any session select and a select or a counter sends the W3 params', async () => {
  await mountFeed(FOLD_FEED);
  history.replaceState(null, '', '#automations/session/ses-1');
  takeAddress();
  await settle();
  expect(q<HTMLSelectElement>('#f-where').value).toBe('s:ses-1');
  expect(stub.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ automation_id: ['aut_a'] }));
  setFilters({ status: 'failed' });
  await settle();
  expect(stub.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ status: ['failed'], automation_id: ['aut_a'] }));
  togglePressed('failed_24h');
  await settle();
  expect(stub.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ counter: ['failed_24h'] }));
});

test('a feed that could not be read says so and offers try again', async () => {
  stub.listFeed.mockRejectedValue(new Error('boom'));
  data.automations = [automation()] as never;
  await loadFeed({});
  app = mount(FeedTab, { target: document.body });
  await settle();
  const again = all('button').filter((b) => b.textContent?.trim() === 'try again');
  expect(again.length).toBeGreaterThan(0);
  stub.listFeed.mockResolvedValue({ runs: FOLD_FEED, total: 5, next_before: null });
  again[0]!.click();
  await settle();
  expect(all('[data-run]').length).toBeGreaterThan(0);
});

test('an attachment is a link to the run attachment route with its name encoded', async () => {
  await mountFeed([run('a1', 1, { attachments: [{ name: 'out put.csv', bytes: 12, mime: 'text/csv' }] })]);
  const link = q<HTMLAnchorElement>('[data-attachment]');
  expect(link.getAttribute('href')).toBe('/api/v1/automations/runs/a1/attachments/out%20put.csv');
  expect(link.hasAttribute('download')).toBe(true);
});
