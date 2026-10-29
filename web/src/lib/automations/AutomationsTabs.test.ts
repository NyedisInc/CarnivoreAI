/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(),
  listTargets: vi.fn(),
  getRunCounts: vi.fn(),
  getRun: vi.fn(),
  listFeed: vi.fn(),
  listRuns: vi.fn(),
  setSchedulerPaused: vi.fn(),
  listProjectChoices: vi.fn(),
  listSessionRecords: vi.fn(),
  readLog: vi.fn(),
  putLogSettings: vi.fn(),
  previewSchedule: vi.fn().mockResolvedValue({ ok: true, fires: [] }),
  listChanges: vi.fn().mockResolvedValue({ changes: [] }),
}));
vi.mock('./api', () => stub);
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import AutomationsScreen from './AutomationsScreen.svelte';
import { feed } from './feed-store.svelte';
import { closePane, data, openInAdvanced } from './page-store.svelte';

const targets = { kinds: ['recipe', 'command'], commands: ['/usr/bin/git pull --ff-only'], recipes: [{ recipe: 'scrooge', params_schema: { properties: {} } }] };
const base = {
  trigger: { cron: '0 7 * * 1', timezone: 'local' }, delivery: { notify: true, notify_on: null }, revision: 1, last_run: null, next_fire_at: 1_900_000_000,
  description: '', project_id: null, misfire: 'skip', retry_max: 0, retry_backoff_s: 300, max_runtime_s: null, retry_due_at: null, enabled: true,
  created_at: 1_800_000_000, updated_at: 1_800_000_000, created_by: 'app', created_actor: { kind: 'app' }, updated_by: 'app', updated_actor: { kind: 'app' },
};
const automations = [
  { ...base, automation_id: 'aut_n', name: 'loose report', target: { kind: 'recipe', recipe: 'scrooge', params: {} } },
  { ...base, automation_id: 'aut_p', name: 'site report', project_id: 7, target: { kind: 'recipe', recipe: 'scrooge', params: {} } },
];
const counts = (over: Record<string, number> = {}) => ({
  now: 1_800_000_000,
  counters: Object.fromEntries(
    ['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you'].map((id, i) => [id, { count: over[id] ?? i, automation_ids: [] }]),
  ),
  hosts: ['studio'],
  has_unrecorded_host: false,
  next_change_at: null,
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const tabIds = () => [...document.querySelectorAll('.ap-toptabs [role="tab"][data-tab]')].map((el) => el.getAttribute('data-tab'));
const subTabIds = () => [...document.querySelectorAll('.ap-subtabs [role="tab"][data-tab]')].map((el) => el.getAttribute('data-tab'));
const show = () => (app as unknown as { show: () => void }).show();

async function mountPage(remembered?: string, top: 'automations' | 'sessions' | 'advanced' = 'advanced'): Promise<void> {
  if (remembered) localStorage.setItem('carnivore.tabs.automations', remembered);
  data.top = top;
  data.tab = 'automations';
  app = mount(AutomationsScreen, { target: document.body, props: { embedded: true } });
  await settle();
}

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: [] });
  stub.listChanges.mockResolvedValue({ changes: [] });
  stub.listAutomations.mockResolvedValue({ automations, scheduler: { paused: false }, tz: 'America/New_York' });
  stub.listTargets.mockResolvedValue(targets);
  stub.getRunCounts.mockResolvedValue(counts({ failed_24h: 2, waiting_on_you: 1, running: 0 }));
  stub.listFeed.mockResolvedValue({ runs: [], total: 0, next_before: null });
  stub.listRuns.mockResolvedValue({ runs: [] });
  stub.listProjectChoices.mockResolvedValue([{ id: 7, name: 'site', folder: '/x/site' }]);
  stub.listSessionRecords.mockResolvedValue([{ session_uuid: 'u-1', name: 'api work', project_id: 7, lifecycle: 'running' }]);
  stub.readLog.mockResolvedValue({ lines: [], settings: { rotate: 'size', max_mb: 10, keep: 5 } });
  data.status = 'loading';
  data.automations = [];
  data.targets = null;
  data.counts = null;
  data.selectedId = null;
  data.paneOpen = false;
  data.paneTab = 'overview';
  data.paneRunId = null;
  data.paneMode = null;
  data.pressed = {};
  data.where = '';
  data.pendingEdit = null;
  data.drawer = null;
  data.projects = [];
  data.sessions = [];
  data.sessionsWanted = false;
  data.notice = '';
  feed.status = 'idle';
  feed.runs = [];
  localStorage.clear();
  history.replaceState(null, '', '#automations');
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the page root is the shared Page frame: one .oc-page with the standard title bar holding the sentence and the actions (T-1)', async () => {
  await mountPage();
  const root = q('[data-automations]');
  expect(root.classList.contains('oc-page')).toBe(true);
  const bar = root.querySelector('header.oc-titlebar')!;
  expect(bar.querySelector('h1.oc-titlebar__title')?.textContent).toBeTruthy();
  expect(bar.querySelector('[data-automation-new]')).not.toBeNull();
  expect(bar.querySelectorAll('button')).toHaveLength(1);
  expect(bar.querySelector('[data-header-sentence]')).toBeNull();
  expect(q('[data-ap-advanced-head] [data-header-sentence]')).not.toBeNull();
  expect(root.querySelector('.oc-page__tabs [role="tab"][data-tab]')).not.toBeNull();
  expect(root.querySelector('.pl-titlebar:not(.ap-pn-bar):not(.ap-dr-bar):not(.ap-adv-head)')).toBeNull();
});

test('exactly three tabs, and a remembered huddle tab opens automations', async () => {
  await mountPage('huddle', 'automations');
  expect(tabIds()).toEqual(['automations', 'sessions', 'advanced']);
  expect(q('.ap-toptabs [data-tab="automations"]').getAttribute('aria-selected')).toBe('true');
  expect(document.querySelector('[data-huddle-list], [data-tab="huddle"]')).toBeNull();
});

test('the sessions tab badge is the unread count of the loaded feed', async () => {
  stub.listFeed.mockResolvedValue({
    runs: [{ run_id: 'run_a', automation_id: 'aut_n', status: 'succeeded', created_at: 1_800_000_100 }],
    total: 1,
    next_before: null,
  });
  await mountPage(undefined, 'automations');
  expect(q('.ap-toptabs [data-tab="sessions"] .oc-ptab__badge').textContent).toContain('1 to review');
  expect(document.querySelector('.ap-toptabs [data-tab="advanced"] .oc-ptab__badge')).toBeNull();
});

test('advanced holds the counters, the table, the run feed, the log button, the commands and the pause switch', async () => {
  await mountPage();
  expect(subTabIds()).toEqual(['automations', 'sessions']);
  for (const sel of ['[data-ct="failed_24h"]', '[data-automations-tab] .ap-list', '[data-automation-log-toggle]', '[data-scheduler-pause-switch]', '.ap-cmd-wrap', '[data-header-sentence]']) {
    expect(document.querySelector(sel), sel).not.toBeNull();
  }
  q('.ap-subtabs [data-tab="sessions"]').click();
  await settle();
  expect(document.querySelector('[data-automations-tab]')).toBeNull();
  expect(data.tab).toBe('sessions');
  expect(q('.ap-subtabs [data-tab="sessions"]').getAttribute('aria-selected')).toBe('true');
});

test('the editor opened from the title strip is seen on the overview, and openInAdvanced lands on the row and on the run', async () => {
  await mountPage(undefined, 'automations');
  q('[data-automation-new]').click();
  await settle();
  expect(data.top).toBe('automations');
  expect(data.paneOpen).toBe(true);
  expect(q('[data-automations]').hasAttribute('data-pane-open')).toBe(true);
  expect(document.querySelector('.ap-pn')).not.toBeNull();
  closePane();
  openInAdvanced('automation', 'aut_p');
  await settle();
  expect(data.top).toBe('advanced');
  expect(data.tab).toBe('automations');
  expect(data.selectedId).toBe('aut_p');
  expect(data.paneOpen).toBe(true);
  openInAdvanced('run', 'run_z');
  await settle();
  expect(data.tab).toBe('sessions');
  expect(data.feedRunId).toBe('run_z');
  expect(data.paneOpen).toBe(false);
});

test('the counter numbers come from the server run-counts route, in the fixed order, with tones only above zero', async () => {
  await mountPage();
  expect(stub.getRunCounts).toHaveBeenCalled();
  const ids = [...document.querySelectorAll('[data-ct]')].map((el) => el.getAttribute('data-ct'));
  expect(ids).toEqual(['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you']);
  expect(q('[data-ct="failed_24h"] [data-ct-n]').textContent).toBe('2');
  expect(q('[data-ct="failed_24h"]').getAttribute('data-tone')).toBe('bad');
  expect(q('[data-ct="waiting_on_you"]').getAttribute('data-tone')).toBe('wait');
  expect(q('[data-ct="running"] [data-ct-n]').textContent).toBe('0');
  expect(q('[data-ct="running"]').getAttribute('data-tone')).toBeNull();
});

test('a counter pressed on one tab shows pressed on the other, and a second press clears it', async () => {
  await mountPage();
  q('[data-ct="failed_24h"]').click();
  await settle();
  expect(q('[data-ct="failed_24h"]').getAttribute('aria-pressed')).toBe('true');
  q('.ap-subtabs [data-tab="sessions"]').click();
  await settle();
  expect(q('[data-ct="failed_24h"]').getAttribute('aria-pressed')).toBe('true');
  expect(stub.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ counter: ['failed_24h'] }));
  q('[data-ct="failed_24h"]').click();
  await settle();
  expect(q('[data-ct="failed_24h"]').getAttribute('aria-pressed')).toBe('false');
});

test('the chosen tab is remembered on this device, the workbench sub-tab under its own key', async () => {
  await mountPage(undefined, 'automations');
  q('.ap-toptabs [data-tab="sessions"]').click();
  await settle();
  expect(localStorage.getItem('carnivore.tabs.automations')).toBe('sessions');
  q('.ap-toptabs [data-tab="advanced"]').click();
  await settle();
  expect(localStorage.getItem('carnivore.tabs.automations')).toBe('advanced');
  q('.ap-subtabs [data-tab="sessions"]').click();
  await settle();
  expect(localStorage.getItem('carnivore.tabs.automations-advanced')).toBe('sessions');
});

test('a paused scheduler shows the banner and the pause switch PUTs the new state (#1495)', async () => {
  stub.listAutomations.mockResolvedValue({ automations, scheduler: { paused: true }, tz: 'America/New_York' });
  stub.setSchedulerPaused.mockResolvedValue({ paused: false });
  await mountPage();
  expect(document.querySelector('[data-scheduler-paused]')).not.toBeNull();
  expect(q('[data-scheduler-pause-switch]').getAttribute('aria-checked')).toBe('true');
  expect(q('[data-header-sentence]').textContent).toContain('scheduler paused');
  stub.listAutomations.mockResolvedValue({ automations, scheduler: { paused: false }, tz: 'America/New_York' });
  q('[data-scheduler-pause-switch]').click();
  await settle();
  expect(stub.setSchedulerPaused).toHaveBeenCalledWith(false);
  expect(document.querySelector('[data-scheduler-paused]')).toBeNull();
});

test('#automations/session/<uuid> opens the workbench run feed with the any-session filter on that session', async () => {
  await mountPage(undefined, 'automations');
  location.hash = '#automations/session/u-1';
  show();
  await settle();
  expect(data.top).toBe('advanced');
  expect(data.tab).toBe('sessions');
  expect(data.where).toBe('s:u-1');
  expect(q('.ap-subtabs [data-tab="sessions"]').getAttribute('aria-selected')).toBe('true');
  expect(location.hash).toBe('#automations');
});

test('#automations/run/<id> selects that run\'s automation with the pane on the output tab at that run', async () => {
  stub.getRun.mockResolvedValue({ run_id: 'run_x', automation_id: 'aut_p', status: 'failed', report: null });
  await mountPage(undefined, 'automations');
  location.hash = '#automations/run/run_x';
  show();
  await settle();
  expect(stub.getRun).toHaveBeenCalledWith('run_x');
  expect(data.top).toBe('advanced');
  expect(data.selectedId).toBe('aut_p');
  expect(data.paneOpen).toBe(true);
  expect(data.paneTab).toBe('output');
  expect(data.paneRunId).toBe('run_x');
  expect(q('[data-selected-automation]').getAttribute('data-selected-automation')).toBe('aut_p');
  expect(location.hash).toBe('#automations/run/run_x');
  closePane();
  expect(location.hash).toBe('#automations');
});

test('#automations/edit/<id> selects that automation and opens the editor in the workbench', async () => {
  await mountPage(undefined, 'automations');
  location.hash = '#automations/edit/aut_p';
  show();
  await settle();
  expect(data.top).toBe('advanced');
  expect(data.selectedId).toBe('aut_p');
  expect(data.paneMode).toBe('edit');
  expect(data.paneOpen).toBe(true);
  expect(location.hash).toBe('#automations');
});

test('switching to the run feed or the sessions tab closes the open pane and takes data-pane-open off the page (mockup setTab)', async () => {
  await mountPage(undefined, 'automations');
  location.hash = '#automations/edit/aut_p';
  show();
  await settle();
  expect(q('[data-automations]').hasAttribute('data-pane-open')).toBe(true);
  (q('.ap-toptabs [data-tab="sessions"]') as HTMLElement).click();
  await settle();
  expect(data.paneOpen).toBe(false);
  expect(q('[data-automations]').hasAttribute('data-pane-open')).toBe(false);
  expect(document.querySelector('.ap-pn')).toBeNull();
});

test('the scheduler log dock sits between the list and the newest-run line and scrolls itself into view (mockup m1-index.html:1342, :3474)', async () => {
  const reveal = vi.fn();
  Element.prototype.scrollIntoView = reveal;
  await mountPage();
  (q('[data-automation-log-toggle]') as HTMLElement).click();
  await settle();
  const order = ['.ap-list', '[data-automation-log]', '[data-auto-preview]', '[data-auto-keys]'].map((sel) => q(sel));
  for (let i = 1; i < order.length; i++) expect(order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(reveal).toHaveBeenCalledWith(expect.objectContaining({ block: 'nearest' }));
});
