/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(), listTargets: vi.fn(), getRunCounts: vi.fn(), listRuns: vi.fn(), previewSchedule: vi.fn(), getRun: vi.fn(),
  updateAutomation: vi.fn(), runAutomationNow: vi.fn(), listProjectChoices: vi.fn(), listSessionRecords: vi.fn(), listFeed: vi.fn(),
}));
vi.mock('../api', () => stub);
vi.mock('../../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import ItemDrawer from './ItemDrawer.svelte';
import { closeDrawer, data, openDrawer } from '../page-store.svelte';

const NOW = 1_800_000_000;
const runRow = (id: string, extra: Record<string, unknown> = {}) => ({
  run_id: id, automation_id: 'aut_a', trigger: 'schedule', slot_at: NOW - 600, status: 'succeeded', reason: null, skip_count: null, first_slot_at: null, last_slot_at: null,
  started_at: NOW - 600, ended_at: NOW - 598, cost_usd: null, error: null, has_report: false, number: 2, title: 'finished with no problems', summary: 'the command printed nothing.',
  attachments: [{ name: 'out.txt', bytes: 12, mime: 'text/plain' }], ...extra,
});
const auto = {
  automation_id: 'aut_a', name: 'alpha', enabled: true, trigger: { cron: '*/15 * * * *', timezone: 'local' }, delivery: { notify: true, notify_on: null }, revision: 7,
  next_fire_at: NOW + 540, description: '', project_id: null, median_took_s: 2, newest_output_empty: false, run_count: 2, newest_number: 2, spends: false,
  files_under: { session_uuid: null, project_id: null }, target: { kind: 'command', command: '/usr/bin/true' }, recent: [],
};

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

beforeEach(async () => {
  vi.clearAllMocks();
  stub.listRuns.mockResolvedValue({ runs: [runRow('r2'), runRow('r1', { number: 1 })] });
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: [1, 2, 3, 4, 5].map((n) => ({ utc: new Date((NOW + n * 900) * 1000).toISOString(), local: '' })) });
  stub.getRun.mockResolvedValue({ ...runRow('r2'), report: null });
  data.status = 'ready';
  data.fixture = false;
  data.automations = [auto] as never;
  data.targets = { kinds: ['command'], recipes: [], commands: [] };
  data.paused = false;
  data.top = 'automations';
  data.drawer = null;
  data.paneOpen = false;
  data.paneMode = null;
  data.now = NOW;
  app = mount(ItemDrawer, { target: document.body });
  await settle();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  data.drawer = null;
});

test('automation mode: open in advanced and edit call the store with this id and close the drawer', async () => {
  openDrawer('automation', 'aut_a');
  await settle();
  expect(q('[data-dr-name]').textContent).toBe('alpha');
  expect(q('[data-dr-title]').textContent).toBe('finished with no problems');
  expect(document.querySelectorAll('[data-dr-fires] [role="listitem"]')).toHaveLength(3);
  q<HTMLButtonElement>('[data-dr-adv="aut_a"]').click();
  await settle();
  expect(data.drawer).toBeNull();
  expect(data.top).toBe('advanced');
  expect(data.tab).toBe('automations');
  expect(data.selectedId).toBe('aut_a');
  expect(data.paneOpen).toBe(true);
  expect(data.paneMode).toBeNull();

  data.top = 'automations';
  openDrawer('automation', 'aut_a');
  await settle();
  q<HTMLButtonElement>('[data-dr-edit="aut_a"]').click();
  await settle();
  expect(data.drawer).toBeNull();
  expect(data.paneMode).toBe('edit');
  expect(data.selectedId).toBe('aut_a');
});

test('Escape closes the drawer and focus goes back to what opened it', async () => {
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  openDrawer('automation', 'aut_a');
  await settle();
  expect(q('[data-ap-drawer]').hasAttribute('data-open')).toBe(true);
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await settle();
  expect(data.drawer).toBeNull();
  expect(q('[data-ap-drawer]').hasAttribute('data-open')).toBe(false);
  expect(document.activeElement).toBe(opener);
});

test('run mode shows the title and summary, and full report in advanced opens the run feed on it', async () => {
  openDrawer('run', 'r2');
  await settle();
  expect(q('[data-dr-title]').textContent).toBe('finished with no problems');
  expect(q('[data-dr-summary]').textContent).toBe('the command printed nothing.');
  expect(document.querySelectorAll('[data-dr-attachments] [role="listitem"]')).toHaveLength(1);
  q<HTMLButtonElement>('[data-dr-adv-run="r2"]').click();
  await settle();
  expect(data.drawer).toBeNull();
  expect(data.top).toBe('advanced');
  expect(data.tab).toBe('sessions');
  expect(data.feedRunId).toBe('r2');
  closeDrawer();
});
