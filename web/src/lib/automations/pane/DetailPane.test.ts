/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { ApiError } from '../../../opscenter/api/auth.svelte';
import { installPopoverPolyfill } from '../../popover-jsdom-polyfill';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(),
  listTargets: vi.fn(),
  getRunCounts: vi.fn(),
  listRuns: vi.fn(),
  listChanges: vi.fn(),
  listProjectChoices: vi.fn(),
  listSessionRecords: vi.fn(),
  updateAutomation: vi.fn(),
  previewSchedule: vi.fn(),
  getRun: vi.fn(),
  readLog: vi.fn(),
  listClaudeLogins: vi.fn(),
  listAnthropicKeys: vi.fn(),
  cancelRun: vi.fn(),
  continueRun: vi.fn(),
  fixFinding: vi.fn(),
  runAutomationNow: vi.fn(),
}));
vi.mock('../api', () => stub);
vi.mock('../../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));
vi.mock('../../blueprints/api', () => ({ listBlueprints: vi.fn().mockResolvedValue({ status: 'ok', blueprints: [] }) }));
vi.mock('../../../opscenter/api/host', () => ({ openSession: vi.fn(() => true), openSessions: vi.fn(() => true), primarySessionId: () => '' }));

installPopoverPolyfill();

import DetailPane from './DetailPane.svelte';
import { data, takeAddress } from '../page-store.svelte';
import { pane } from './pane-data.svelte';
import { reports } from '../feed-store.svelte';

const NOW = 1_800_000_000;
const run = (n: number, status: string, over: Record<string, unknown> = {}) => ({
  run_id: `r${n}`, automation_id: 'aut_a', number: n, status, reason: null, trigger: 'schedule', attempt: null, slot_at: NOW - 3600 * n,
  started_at: NOW - 3600 * n, ended_at: NOW - 3600 * n + 2, skip_count: null, first_slot_at: null, last_slot_at: null, report_bytes: 40, output_empty: false,
  has_report: true, error: null, cost_usd: null, host: 'studio', usage: null, delivered: null, attachments: null, sessions: [], report: { summary: `run ${n}` }, ...over,
});
const automation = (over: Record<string, unknown> = {}) => ({
  automation_id: 'aut_a', name: 'alpha', enabled: true, trigger: { cron: '0 7 * * 1', timezone: 'UTC' }, delivery: { notify: true, notify_on: null },
  revision: 1, last_run: null, next_fire_at: NOW + 600, description: '', project_id: null, misfire: 'run_once', retry_max: 0, retry_backoff_s: 300,
  max_runtime_s: null, median_took_s: 2, newest_output_empty: false, run_count: 3, newest_number: 3, spends: false, recent: [],
  files_under: { session_uuid: null, project_id: null }, target: { kind: 'command', command: '/usr/bin/git pull', project_id: null },
  created_at: NOW - 9000, updated_at: NOW - 100, created_actor: { kind: 'app' }, updated_actor: { kind: 'app' }, ...over,
});
const targets = { kinds: ['command'], commands: ['/usr/bin/git pull'], recipes: [] };

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const key = async (k: string) => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  await settle();
};
const mountPane = async (runs: unknown[], over: Record<string, unknown> = {}) => {
  stub.listRuns.mockResolvedValue({ runs });
  data.automations = [automation(over)] as never;
  data.selectedId = 'aut_a';
  data.paneOpen = true;
  app = mount(DetailPane, { target: document.body });
  await settle();
};

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.listChanges.mockResolvedValue({ changes: [] });
  stub.readLog.mockResolvedValue({ lines: [], settings: { rotate: 'size', max_mb: 10, keep: 5 } });
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: [] });
  stub.listClaudeLogins.mockResolvedValue([]);
  stub.listAnthropicKeys.mockResolvedValue([]);
  stub.listAutomations.mockResolvedValue({ automations: [automation({ revision: 2 })], scheduler: { paused: false }, tz: 'UTC' });
  stub.listTargets.mockResolvedValue(targets);
  stub.getRunCounts.mockRejectedValue(new Error('no route'));
  stub.listProjectChoices.mockResolvedValue([]);
  Object.assign(data, {
    status: 'ready', error: '', tz: 'UTC', now: NOW, paused: false, counts: null, targets, projects: [], sessions: [], selectedId: null,
    paneOpen: false, paneTab: 'output', paneRunId: null, paneMode: null, seed: null, notice: '',
  });
  pane.automationId = null;
  pane.runs = [];
  for (const k of Object.keys(reports)) delete reports[k];
  history.replaceState(null, '', '#automations');
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('a run link opens the output tab at that run and closing the pane takes the run off the address', async () => {
  stub.getRun.mockResolvedValue(run(2, 'succeeded'));
  data.automations = [automation()] as never;
  stub.listRuns.mockResolvedValue({ runs: [run(3, 'succeeded'), run(2, 'succeeded'), run(1, 'succeeded')] });
  app = mount(DetailPane, { target: document.body });
  history.replaceState(null, '', '#automations/run/r2');
  takeAddress();
  await settle();
  expect(q('[data-detail-pane]').hasAttribute('data-open')).toBe(true);
  expect(q('[data-pane-body]').getAttribute('data-pane-body')).toBe('output');
  expect(q('[data-step-n]').textContent).toBe('#2 of 3');
  expect(location.hash).toBe('#automations/run/r2');
  q('[data-pane-x]').click();
  await settle();
  expect(location.hash).toBe('#automations');
  expect(q('[data-detail-pane]').hasAttribute('data-open')).toBe(false);
});

test('[ steps to the older run and ] to the newer one', async () => {
  await mountPane([run(3, 'succeeded'), run(2, 'succeeded'), run(1, 'succeeded')]);
  expect(q('[data-step-n]').textContent).toBe('#3 of 3');
  await key('[');
  expect(q('[data-step-n]').textContent).toBe('#2 of 3');
  expect(data.paneRunId).toBe('r2');
  await key('[');
  expect(q('[data-step-n]').textContent).toBe('#1 of 3');
  await key(']');
  expect(q('[data-step-n]').textContent).toBe('#2 of 3');
});

test('a save that met a newer revision reads again and says it changed elsewhere', async () => {
  await mountPane([run(3, 'succeeded')]);
  data.paneMode = 'edit';
  await settle();
  stub.updateAutomation.mockRejectedValue(new ApiError('conflict', 409, 'revision_conflict', { detail: { code: 'revision_conflict' } }));
  q('[data-editor-save]').click();
  await settle();
  expect(data.notice).toBe('alpha changed elsewhere, reloaded');
  expect(stub.listAutomations).toHaveBeenCalled();
  expect(document.querySelector('[data-editor-problem]')).toBeNull();
});

test('the runs tab folds identical runs, reads the skip sentence, and says not measured for a null usage', async () => {
  const same = { summary: 'same' };
  const skipped = run(3, 'skipped', { reason: 'missed_slot', skip_count: 3, first_slot_at: NOW - 3 * 86400, last_slot_at: NOW - 86400, has_report: false, report_bytes: null, report: undefined });
  await mountPane([run(6, 'succeeded', { report: same }), run(5, 'succeeded', { report: same, usage: { input: 1, output: 2, cache: 3, total: 12345 } }), run(4, 'succeeded', { report: same }), skipped], { run_count: 6, newest_number: 6 });
  q('[data-tab="runs"]').click();
  await settle();
  const rows = () => [...document.querySelectorAll('[data-rr]')].map((r) => r.getAttribute('data-rr'));
  expect(rows()).toEqual(['r6', 'r3']);
  expect(q('[data-rr="r6"] [data-run-tokens]').textContent).toBe('not measured');
  expect(q('[data-rr="r3"] [data-run-line]').textContent).toContain('skipped 3 times');
  expect(q('[data-rr="r3"] [data-run-line]').textContent).toContain('the computer was asleep or the app was off at the scheduled time');
  const toggle = q<HTMLButtonElement>('[data-fold="r6"]');
  expect(toggle.textContent).toContain('x3');
  toggle.click();
  await settle();
  expect(rows()).toEqual(['r6', 'r5', 'r4', 'r3']);
  expect(q('[data-rr="r5"] [data-run-tokens]').textContent).toBe('12,345');
  toggle.click();
  await settle();
  expect(rows()).toEqual(['r6', 'r3']);
});

test('the action row shows cancel on a live run only', async () => {
  await mountPane([run(2, 'running', { has_report: false, report_bytes: null, report: undefined, ended_at: null }), run(1, 'succeeded')], { run_count: 2, newest_number: 2 });
  expect(document.querySelector('[data-act="cancel"]')).not.toBeNull();
  expect(document.querySelector('[data-act="run"]')).toBeNull();
  await key('[');
  expect(q('[data-step-n]').textContent).toBe('#1 of 2');
  expect(document.querySelector('[data-act="cancel"]')).toBeNull();
  expect(document.querySelector('[data-act="run"]')).not.toBeNull();
});

test('delete asks in a popup under the kebab: the actions stay, Escape and cancel answer no, focus goes back to the kebab', async () => {
  await mountPane([run(1, 'succeeded')]);
  const kebab = q<HTMLButtonElement>('[data-pane-kebab]');
  const ask = async () => {
    kebab.click();
    await settle();
    [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => /delete/.test(item.textContent ?? ''))!.click();
    await settle();
  };
  await ask();
  const popup = q('[data-pane-delete]');
  expect(popup.getAttribute('role')).toBe('alertdialog');
  expect(popup.classList.contains('popup-focus')).toBe(true);
  expect(document.querySelector('[data-pane-edit]')).not.toBeNull();
  expect(document.activeElement).toBe(q('[data-pane-delete-no]'));
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await settle();
  expect(document.querySelector('[data-pane-delete]')).toBeNull();
  expect(q('[data-detail-pane]').hasAttribute('data-open')).toBe(true);
  expect(document.activeElement).toBe(kebab);
  await ask();
  q('[data-pane-delete-no]').click();
  await settle();
  expect(document.querySelector('[data-pane-delete]')).toBeNull();
});

test('a report draws through the report renderer with a fix-it button only where a fix prompt exists', async () => {
  const report = {
    items: [
      { label: 'api: mostly the top model', status: 'fail', fix_prompt: 'look at it', finding_id: 'f1' },
      { label: 'api: no fix here', status: 'fail', fix_prompt: 'look too' },
    ],
  };
  await mountPane([run(1, 'succeeded', { report })], { run_count: 1, newest_number: 1 });
  expect(document.querySelectorAll('[data-fix]')).toHaveLength(1);
  expect(q('[data-fix]').getAttribute('data-fix')).toBe('f1');
  stub.fixFinding.mockResolvedValue({ id: 'ses_1', tmux_session: 'carnivore_x' });
  q('[data-fix]').click();
  await settle();
  expect(stub.fixFinding).toHaveBeenCalledWith('r1', 'f1');
});

test('the log tab reads a machine reason in words and the overview change log reads a target edit in words', async () => {
  stub.readLog.mockResolvedValue({
    lines: [{ ts: NOW - 60, event: 'finished', status: 'failed', reason: 'exit_1', automation_id: 'aut_a', run_id: 'r3' }],
    settings: { rotate: 'size', max_mb: 10, keep: 5 },
  });
  stub.listChanges.mockResolvedValue({
    changes: [{ seq: 1, automation_id: 'aut_a', action: 'update', at: NOW - 30, actor: { kind: 'app' }, changes: [
      { field: 'target', before: { kind: 'command', command: '/usr/bin/git pull', project_id: null }, after: { kind: 'recipe', recipe: 'x'.repeat(120) } },
    ] }],
  });
  await mountPane([run(3, 'failed')]);
  data.paneTab = 'overview';
  await settle();
  const changes = q('[data-change-log]').textContent ?? '';
  expect(changes).not.toContain('{');
  expect(changes).not.toContain('"kind"');
  data.paneTab = 'log';
  await settle();
  const log = q('[data-log-lines]').textContent ?? '';
  expect(log).toContain('the command exited with code 1');
  expect(log).not.toContain('exit_1');
});
