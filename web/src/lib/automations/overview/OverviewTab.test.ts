/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(), listTargets: vi.fn(), getRunCounts: vi.fn(), listRuns: vi.fn(), listProjectChoices: vi.fn(), listSessionRecords: vi.fn(),
  updateAutomation: vi.fn(), runAutomationNow: vi.fn(), createAutomation: vi.fn(), deleteAutomation: vi.fn(), getRun: vi.fn(), listFeed: vi.fn(),
}));
vi.mock('../api', () => stub);
vi.mock('../../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import OverviewTab from './OverviewTab.svelte';
import { data } from '../page-store.svelte';
import { overview } from './overview-state.svelte';

const NOW = 1_800_000_000;
const run = (n: number, status: string) => ({
  run_id: `r${n}`, number: n, status, reason: null, trigger: 'schedule', attempt: null, slot_at: NOW - 600, started_at: NOW - 600, ended_at: NOW - 598,
  skip_count: null, report_bytes: 1, output_empty: false,
});
const row = (id: string, name: string, cron: string, recent: unknown[], over: Record<string, unknown> = {}) => ({
  automation_id: id, name, enabled: true, trigger: { cron, timezone: 'local' }, delivery: { notify: true, notify_on: null }, revision: 7, next_fire_at: NOW + 540,
  description: '', project_id: null, median_took_s: 2, newest_output_empty: false, run_count: 1, newest_number: 1, spends: false, last_run: null,
  files_under: { session_uuid: null, project_id: null }, target: { kind: 'command', command: '/usr/bin/true' }, recent, ...over,
});
const counts = () => ({
  now: NOW, hosts: [], has_unrecorded_host: false, next_change_at: null,
  counters: Object.fromEntries(
    ['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you'].map((id) => [id, { count: 0, automation_ids: [] }]),
  ),
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

beforeEach(async () => {
  vi.clearAllMocks();
  const list = [row('aut_a', 'alpha', '*/15 * * * *', [run(1, 'succeeded')]), row('aut_b', 'bravo', '0 9 * * 1', [run(1, 'failed')])];
  stub.listAutomations.mockResolvedValue({ automations: list, scheduler: { paused: false }, tz: 'UTC' });
  stub.listTargets.mockResolvedValue({ kinds: ['command'], recipes: [], commands: [] });
  stub.getRunCounts.mockResolvedValue(counts());
  stub.listProjectChoices.mockResolvedValue([]);
  stub.listSessionRecords.mockResolvedValue([]);
  stub.listFeed.mockResolvedValue({ runs: [], total: 0, next_before: null });
  stub.updateAutomation.mockResolvedValue({});
  data.status = 'ready';
  data.automations = list as never;
  data.targets = { kinds: ['command'], recipes: [], commands: [] };
  data.paused = false;
  data.top = 'automations';
  data.notice = '';
  data.pressed = {};
  overview.find = '';
  overview.pending = {};
  app = mount(OverviewTab, { target: document.body });
  await settle();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the card switch sends {enabled} once at the row revision, and a refusal puts it back with a notice', async () => {
  const sw = q<HTMLButtonElement>('[data-card-switch="aut_a"]');
  expect(sw.getAttribute('aria-checked')).toBe('true');
  stub.updateAutomation.mockRejectedValueOnce(new Error('revision moved'));
  sw.click();
  await settle();
  expect(stub.updateAutomation).toHaveBeenCalledTimes(1);
  expect(stub.updateAutomation).toHaveBeenCalledWith('aut_a', 7, { enabled: false });
  expect(q('[data-card-switch="aut_a"]').getAttribute('aria-checked')).toBe('true');
  expect(data.notice).not.toBe('');
  stub.updateAutomation.mockResolvedValueOnce({});
  data.notice = '';
  let release: () => void = () => {};
  stub.listAutomations.mockReturnValueOnce(new Promise((res) => (release = () => res({ automations: data.automations, scheduler: { paused: false }, tz: 'UTC' }))));
  q('[data-card-switch="aut_a"]').click();
  await settle();
  expect(q('[data-card-switch="aut_a"]').getAttribute('aria-checked')).toBe('false');
  expect(stub.updateAutomation).toHaveBeenLastCalledWith('aut_a', 7, { enabled: false });
  release();
  await settle();
});

test('the failed tile puts the sessions tab up with that counter pressed', async () => {
  q<HTMLButtonElement>('[data-tile-go="failed"]').click();
  await settle();
  expect(data.pressed).toEqual({ failed_24h: true });
  expect(data.top).toBe('sessions');
});

test('every card is three lines, says on or off only in its switch, and keeps the status word with the schedule', () => {
  const cards = [...document.querySelectorAll('section.oc-card[data-card]')];
  expect(cards).toHaveLength(2);
  for (const card of cards) {
    expect(card.children).toHaveLength(3);
    const sw = card.querySelector('[role="switch"]')!;
    expect(sw.textContent?.trim()).toBe(sw.getAttribute('aria-checked') === 'true' ? 'on' : 'off');
    expect(card.textContent?.replace(sw.textContent ?? '', '').toLowerCase()).not.toMatch(/\bon\b/);
  }
  const bravo = q('[data-card="aut_b"]');
  expect(bravo.querySelector('.oc-card__foot .oc-tag')?.textContent).toBe('failed');
  expect(bravo.querySelector('.oc-card__head .oc-tag')?.textContent).not.toBe('failed');
  expect(q('[data-card="aut_a"] .oc-card__foot .oc-tag')).toBeNull();
});
