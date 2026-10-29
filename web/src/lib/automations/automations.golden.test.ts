/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { afterAll, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(), listTargets: vi.fn(), getRunCounts: vi.fn(), listRuns: vi.fn(), listFeed: vi.fn(), listChanges: vi.fn(),
  listProjectChoices: vi.fn(), listSessionRecords: vi.fn(), getRun: vi.fn(), readLog: vi.fn(), putLogSettings: vi.fn(),
  previewSchedule: vi.fn(), listClaudeLogins: vi.fn(), listAnthropicKeys: vi.fn(), setSchedulerPaused: vi.fn(),
  updateAutomation: vi.fn(), createAutomation: vi.fn(), runAutomationNow: vi.fn(), cancelRun: vi.fn(), continueRun: vi.fn(), fixFinding: vi.fn(),
}));
vi.mock('./api', () => stub);
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));
vi.mock('../blueprints/api', () => ({ listBlueprints: vi.fn().mockResolvedValue({ status: 'ok', blueprints: [] }) }));
vi.mock('../../opscenter/api/host', async (orig) => ({ ...(await orig<object>()), openSession: vi.fn(() => true), openSessions: vi.fn(() => true) }));

import AutomationsScreen from './AutomationsScreen.svelte';
import AutomationEditor from './AutomationEditor.svelte';
import RunSheet from './report/RunSheet.svelte';
import { clockFor } from './logic/words';
import { data } from './page-store.svelte';
import { view } from './list-state.svelte';
import { boundary, feed, loadFeed, reports } from './feed-store.svelte';
import { unread } from './read-state.svelte';
import { fv } from './feed/feed-state.svelte';
import { pane } from './pane/pane-data.svelte';

const GOLDEN = path.join(__dirname, '__goldens__', 'automations-dom.json');
const NOW = 1_800_000_000;
const recorded: Record<string, string> = fs.existsSync(GOLDEN) ? JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) : {};
const taken: Record<string, string> = {};

const run = (n: number, status: string, over: Record<string, unknown> = {}) => ({
  run_id: `r${n}`, automation_id: 'aut_a', automation_name: 'alpha', number: n, status, reason: null, trigger: 'schedule', attempt: null,
  slot_at: NOW - 3600 * n, started_at: NOW - 3600 * n, ended_at: NOW - 3600 * n + 2, skip_count: null, first_slot_at: null,
  last_slot_at: null, report_bytes: 40, output_empty: false, has_report: true, error: null, cost_usd: null, host: 'studio',
  usage: null, delivered: null, attachments: null, sessions: [], report: { summary: `run ${n}` }, ...over,
});
const base = {
  trigger: { cron: '0 7 * * 1', timezone: 'UTC' }, delivery: { notify: true, notify_on: null }, revision: 1, last_run: null, next_fire_at: null,
  description: '', project_id: null, enabled: true, median_took_s: 2, newest_output_empty: false, run_count: 3, newest_number: 3, spends: false,
  misfire: 'run_once', retry_max: 0, retry_backoff_s: 300, max_runtime_s: null, files_under: { session_uuid: null, project_id: null },
  created_at: NOW - 9000, updated_at: NOW - 100, created_actor: { kind: 'app' }, updated_actor: { kind: 'app' },
  target: { kind: 'command', command: '/usr/bin/git pull', project_id: null },
};
const auto = (id: string, name: string, recent: unknown[], over: Record<string, unknown> = {}) => ({ ...base, automation_id: id, name, recent, ...over });
const automations = () => [
  auto('aut_a', 'alpha ok', [run(3, 'succeeded'), run(2, 'succeeded'), run(1, 'failed')], { next_fire_at: NOW + 600 }),
  auto('aut_b', 'bravo off', [run(1, 'succeeded')], { enabled: false, target: { kind: 'recipe', recipe: 'scrooge', params: {} } }),
  auto('aut_d', 'delta skipped', [run(1, 'skipped')]),
  auto('aut_e', 'echo failed', [run(1, 'failed')], { description: 'weekly cost report', project_id: 7 }),
  auto('aut_f', 'foxtrot waiting', [run(1, 'waiting_on_you')]),
];
const targets = {
  kinds: ['recipe', 'command', 'sequence', 'session_message', 'agent', 'blueprint_launch', 'card'], commands: ['/usr/bin/git pull'],
  recipes: [{ recipe: 'scrooge', params_schema: { properties: { active_days: { type: 'integer', default: 30, minimum: 1, maximum: 90 } } } }],
};
const counts = () => ({
  now: NOW, hosts: ['studio'], has_unrecorded_host: false, next_change_at: null,
  counters: Object.fromEntries(['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you']
    .map((id, i) => [id, { count: i, automation_ids: id === 'failed_24h' ? ['aut_e'] : [] }])),
});

function canonical(root: Element): string {
  const KEEP = /^(role|aria-.*|data-.*|type|href|for|name|placeholder|disabled|checked|selected|hidden|open|value|title|tabindex|colspan)$/;
  const lines: string[] = [];
  const walk = (el: Element, depth: number): void => {
    const cls = [...el.classList].filter((c) => !/^svelte-/.test(c)).sort().join(' ');
    const attrs = [...el.attributes]
      .filter((a) => KEEP.test(a.name))
      .map((a) => `${a.name}=${a.value.replace(/\b(s?\d*-?[a-z]*-?_?[a-z0-9]{6,}-\d+|oc-[a-z-]+-s?[0-9a-z]{4,}|bits-\w+|\w+-\d+-\d+)\b/g, '#').replace(/#-c\d+/g, '#')}`)
      .sort();
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => (n.textContent ?? '').replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ');
    lines.push(`${'  '.repeat(depth)}<${el.tagName.toLowerCase()}${cls ? ` .${cls.replace(/ /g, '.')}` : ''}${attrs.length ? ` [${attrs.join(' ')}]` : ''}>${own ? ` ${own}` : ''}`);
    for (const child of el.children) walk(child, depth + 1);
  };
  for (const child of root.children) walk(child, 0);
  return lines.join('\n');
}

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => {
  for (let i = 0; i < 10; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector<T>(sel)!;
const click = async (sel: string): Promise<void> => { q(sel).click(); await settle(); };

async function snap(name: string): Promise<void> {
  await settle();
  taken[name] = canonical(document.body);
  if (!process.env.UPDATE_GOLDENS) expect(taken[name], `golden ${name}`).toBe(recorded[name]);
}

async function mountScreen(tab: 'automations' | 'sessions' = 'automations'): Promise<void> {
  data.top = 'advanced';
  data.tab = tab;
  app = mount(AutomationsScreen, { target: document.body, props: { embedded: true } });
  await settle();
}

beforeEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.setSystemTime(new Date((NOW + 60) * 1000));
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: [] });
  stub.listChanges.mockResolvedValue({ changes: [] });
  stub.listAutomations.mockResolvedValue({ automations: automations(), scheduler: { paused: false }, tz: 'UTC' });
  stub.listTargets.mockResolvedValue(targets);
  stub.getRunCounts.mockResolvedValue(counts());
  stub.listRuns.mockResolvedValue({ runs: [run(3, 'succeeded'), run(2, 'succeeded'), run(1, 'failed', { error: 'exit 1' })] });
  stub.listFeed.mockResolvedValue({ runs: [], total: 0, next_before: null });
  stub.listProjectChoices.mockResolvedValue([{ id: 7, name: 'site', folder: '/x/site' }]);
  stub.listSessionRecords.mockResolvedValue([{ session_uuid: 'u-1', name: 'api work', project_id: 7, lifecycle: 'running' }]);
  stub.readLog.mockResolvedValue({ lines: [{ ts: NOW - 30, event: 'fired', automation_id: 'aut_a', name: 'alpha ok' }], settings: { rotate: 'size', max_mb: 10, keep: 5 } });
  stub.listClaudeLogins.mockResolvedValue([]);
  stub.listAnthropicKeys.mockResolvedValue([]);
  stub.getRun.mockImplementation(async (id: string) => run(Number(id.slice(1)) || 1, 'succeeded', { run_id: id }));
  Object.assign(data, {
    status: 'loading', error: '', tz: 'UTC', now: NOW, paused: false, counts: null, targets: null, projects: [], sessions: [], sessionsWanted: false,
    selectedId: null, tab: 'automations', paneOpen: false, paneTab: 'overview', paneRunId: null, paneMode: null, seed: null, notice: '', where: '',
    feedRunId: null, pendingEdit: null, pendingNew: null, logOpen: false, commandsOpen: false, automations: [], pressed: {},
    filters: { automation: '', status: '', trigger: '', host: '' },
  });
  Object.assign(feed, { runs: [], total: 0, nextBefore: null, status: 'idle', error: '', loadingMore: false });
  for (const k of Object.keys(reports)) delete reports[k];
  for (const k of Object.keys(boundary)) delete boundary[k];
  Object.assign(fv, { q: '', changedOnly: false, unreadOnly: false, filtersOpen: false, expanded: {}, sheet: false });
  Object.assign(view, { q: '', pills: [], sort: { k: 'light', d: 1 }, dens: 'comfortable', busyId: null });
  pane.automationId = null;
  pane.runs = [];
  unread.seenAt = null;
  unread.read = [];
  localStorage.clear();
  Element.prototype.scrollIntoView = () => {};
  Object.assign(HTMLElement.prototype, { showPopover() {}, hidePopover() {}, togglePopover() { return false; } });
  history.replaceState(null, '', '#automations');
  const require = createRequire(import.meta.url);
  delete (globalThis as Record<string, unknown>).Preferences;
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  for (const file of ['preferences.js', 'preference-bridge.js']) {
    const p = require.resolve(`../../../../client/js/${file}`);
    delete require.cache[p];
    require(p);
  }
  (globalThis as Record<string, unknown>).API = { call: async () => ({ revision: 3, values: {} }) };
});

afterAll(() => {
  if (process.env.UPDATE_GOLDENS) {
    fs.mkdirSync(path.dirname(GOLDEN), { recursive: true });
    fs.writeFileSync(GOLDEN, JSON.stringify(taken, null, 1) + '\n');
  }
});

describe('the list tab', () => {
  test('the list, toolbar and counter strip', async () => {
    await mountScreen();
    await snap('list');
  });
  test('narrowed by a pill and a search, with the clear button', async () => {
    await mountScreen();
    view.pills = [{ k: 'status', v: 'failed' }];
    view.q = 'echo';
    await snap('list-filtered');
  });
  test('compact density, sorted by name descending', async () => {
    await mountScreen();
    view.dens = 'compact';
    view.sort = { k: 'name', d: -1 };
    await snap('list-compact');
  });
  test('paused with a notice', async () => {
    await mountScreen();
    data.paused = true;
    data.notice = 'saved';
    await snap('list-paused');
  });
  test('the row menu open', async () => {
    await mountScreen();
    expect(document.querySelector('[data-kebab][data-rk]'), 'a list row draws no kebab').toBeNull();
    q('[data-automation="aut_a"]').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 40 }));
    await settle();
    expect(document.querySelector('[role="menu"] [data-node="edit"]'), 'the row menu opened').not.toBeNull();
    await snap('list-row-menu');
  });
  test('the log dock open', async () => {
    await mountScreen();
    await click('[data-automation-log-toggle]');
    await snap('list-log-dock');
  });
  test('the commands popover open', async () => {
    await mountScreen();
    data.commandsOpen = true;
    await snap('list-commands-popover');
  });
  test('an empty list', async () => {
    stub.listAutomations.mockResolvedValue({ automations: [], scheduler: { paused: false }, tz: 'UTC' });
    await mountScreen();
    await snap('list-empty');
  });
});

describe('the detail pane', () => {
  for (const tab of ['overview', 'output', 'runs', 'log'] as const) {
    test(`the ${tab} tab`, async () => {
      await mountScreen();
      data.selectedId = 'aut_a';
      data.paneOpen = true;
      data.paneTab = tab;
      await snap(`pane-${tab}`);
    });
  }
  test('the pane editing an automation', async () => {
    await mountScreen();
    data.selectedId = 'aut_a';
    data.paneOpen = true;
    data.paneMode = 'edit';
    await snap('pane-edit');
  });
  test('the pane creating an automation', async () => {
    await mountScreen();
    data.paneOpen = true;
    data.paneMode = 'new';
    await snap('pane-new');
  });
});

describe('the editor', () => {
  const mountEditor = async (automation: unknown): Promise<void> => {
    app = mount(AutomationEditor, { target: document.body, props: { automation: automation as never, targets: targets as never, projects: [{ id: 7, name: 'site', folder: '/x/site' }], onDone: () => {}, onCancel: () => {} } });
    await settle();
  };
  test('a new automation', async () => {
    await mountEditor(null);
    await snap('editor-new');
  });
  for (const [name, target] of [
    ['command', { kind: 'command', command: '/usr/bin/git pull', project_id: null }],
    ['recipe', { kind: 'recipe', recipe: 'scrooge', params: { active_days: 30 } }],
    ['sequence', { kind: 'sequence', steps: [{ kind: 'command', command: '/usr/bin/git pull' }, { kind: 'command', command: '/usr/bin/git pull' }] }],
    ['session_message', { kind: 'session_message', session_uuid: 'u-1', text: 'hello' }],
    ['agent', { kind: 'agent', folder: '/x/site', prompt: 'look', permission: 'edits_in_folder', tools: ['Read', 'Edit'], max_turns: 30, max_budget_usd: 1, timeout_s: 1800 }],
    ['agent_unattended', { kind: 'agent', folder: '/x/site', prompt: 'look', permission: 'unattended', tools: ['Read'], max_turns: 30, max_budget_usd: 1, timeout_s: 1800 }],
    ['blueprint', { kind: 'blueprint_launch', blueprint_uuid: '', members: null }],
    ['card', { kind: 'card', project_id: 7, title: 't', summary: 's', text: 'x', how_to_validate: 'y' }],
  ] as const) {
    test(`editing a ${name} automation`, async () => {
      await mountEditor(auto('aut_x', 'edit me', [], { target }));
      await snap(`editor-${name}`);
    });
  }
});

describe('the sessions feed', () => {
  const FEED = [
    run(5, 'succeeded', { run_id: 'r5', report: { summary: 'c' } }), run(4, 'succeeded', { run_id: 'r4', report: { summary: 'c' } }),
    run(3, 'failed', { run_id: 'r3', error: 'exit 1', report: { exit_code: 1, stderr_tail: 'boom' } }),
    run(2, 'succeeded', { run_id: 'r2', report: { summary: 'b' } }), run(1, 'succeeded', { run_id: 'r1', report: { summary: 'a' } }),
  ];
  const mountFeed = async (): Promise<void> => {
    stub.listFeed.mockResolvedValue({ runs: FEED, total: FEED.length, next_before: null });
    await mountScreen('sessions');
    await loadFeed({});
    await settle();
  };
  test('the feed list', async () => {
    await mountFeed();
    await snap('feed');
  });
  test('the feed with the filters open and a run read', async () => {
    await mountFeed();
    fv.filtersOpen = true;
    data.feedRunId = 'r3';
    await snap('feed-reader');
  });
});

describe('the report sheet', () => {
  const sheet = async (report: unknown, composition: 'pane' | 'reader', status = 'succeeded'): Promise<void> => {
    app = mount(RunSheet, {
      target: document.body,
      props: { run: run(3, status), slot: { state: 'ready', report }, composition, clock: clockFor('UTC'), tz: 'UTC', now: NOW, prev: null, onRetry: undefined } as never,
    });
    await settle();
  };
  const REPORT = {
    summary: '# heading\n- item\n**bold**',
    checks: [{ name: 'api', status: 'ok' }, { name: 'worker', status: 'fail', detail: 'timeout' }],
    items: [{ label: 'has both', status: 'fail', fix_prompt: 'do it', finding_id: 'f1' }],
    stdout_tail: 'out text', stderr_tail: 'err text', exit_code: 1,
  };
  test('a mixed report in the reader composition', async () => {
    await sheet(REPORT, 'reader', 'failed');
    await snap('sheet-reader');
  });
  test('a nested object report draws the tree with its folds', async () => {
    await sheet({ config: { region: 'east', limits: { cpu: 2, mem: { soft: 1, hard: 2 } } }, hosts: { a: { up: true }, b: { up: false } } }, 'reader');
    await snap('sheet-tree');
  });
  test('a mixed report in the pane composition', async () => {
    await sheet(REPORT, 'pane');
    await snap('sheet-pane');
  });
});
