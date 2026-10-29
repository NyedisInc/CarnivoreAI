/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const reads: string[] = [];
let pinnedNow: number | null = null;
let running: unknown[] = [];
let queue: { items: unknown[]; total: number } = { items: [], total: 0 };
let contributed: unknown[] = [];

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    reads.push(path);
    return {
      state: 'behind', lag: { files: 4, seconds: 30 }, last_delivery_at: null, stalled_since: null, rebuilding: [],
      plugins: { stats: { lag: { files: 0, seconds: 0 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0 },
        deepsearch: { lag: { files: 4, seconds: 30 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0 } },
      recent: [
        { plugin: 'deepsearch', kind: 'delivery', scope: 'session', session_uuid: 'u1', session: 'fix login', project_id: 3,
          project: 'carnivore', conversation_id: 'c1', family: 'claude', trigger: 'live', finished_at: (pinnedNow ?? Date.now() / 1000) - 12,
          duration_ms: 4.2, runs: 17, events: 2, outcome: 'ok', error: null },
        { plugin: 'stats', kind: 'delivery', scope: 'machine', session_uuid: null, session: null, project_id: null,
          project: null, conversation_id: 'c2', family: 'claude', trigger: 'plugins', finished_at: (pinnedNow ?? Date.now() / 1000) - 300,
          duration_ms: 1400, runs: 3, events: 9, outcome: 'failed', error: 'KeyError' },
        ...contributed,
      ],
      running,
      queue,
    };
  },
}));

import Cell from './Cell.svelte';
import PipelineStatusPanel from '../../../lib/pipeline-status/PipelineStatusPanel.svelte';
import { META } from '../../engine/meta';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { runTimeWords } from '../../lib/run-chart';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  reads.length = 0;
  pinnedNow = null;
  running = [];
  queue = { items: [], total: 0 };
  contributed = [];
  vi.useRealTimers();
});

function shown(cell: Element): string {
  const copy = cell.cloneNode(true) as Element;
  for (const hidden of copy.querySelectorAll('[data-outcome-words]')) hidden.remove();
  return copy.textContent?.trim() ?? '';
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

function put(component: typeof Cell | typeof PipelineStatusPanel, props: Record<string, unknown>): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(component as never, { target, props }));
  return target;
}

describe('the pipeline widget', () => {
  test('draws a status square per plugin with no rebuild button, the status line beside them, and the chart below', async () => {
    const target = put(Cell, { width: 420, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(target.querySelector('[data-pipeline-cell]')).not.toBeNull();
    expect(target.querySelector('[data-ps="top"] [data-ps="state"]')?.textContent?.trim()).toBe('behind: 4 files, 0m 30s');
    expect([...target.querySelectorAll('[data-ps-square]')].map((el) => el.getAttribute('data-ps-square'))).toEqual(['stats', 'deepsearch']);
    expect([...target.querySelectorAll('[data-ps-square] .ps-sq__mark')].map((el) => el.getAttribute('data-mark'))).toEqual(['ok', 'behind']);
    expect(target.querySelectorAll('[data-ps="rebuild"]')).toHaveLength(0);
    expect(target.querySelector('[role="alert"][data-ps="problem"]')).toBeNull();
    expect(target.querySelector('[data-ps="screen"]')?.classList.contains('ps--compact')).toBe(true);
    const top = target.querySelector('[data-ps="top"]')!;
    const chart = target.querySelector('[data-pipeline-chart]')!;
    expect(chart).not.toBeNull();
    expect(top.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test('the developer widget\'s pipeline tab mounts this same cell', async () => {
    const { MONITORS } = await import('../developer/meta');
    expect(MONITORS.find((tab) => tab.id === 'pipeline')?.component).toBe(Cell);
  });

  test('the chart: one row per area and plugin with its friendly name, area, run time, how long ago and runs', async () => {
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const heads = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-headcell')].map((el) => el.textContent?.trim());
    expect(heads).toEqual(['name', 'area', 'run time', 'ago', 'runs']);
    const rows = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-row')].map((row) =>
      [...row.querySelectorAll('[data-col]')].map(shown));
    expect(rows).toEqual([
      ['deep search', 'fix login', '4 ms', '12s ago', '17'],
      ['stats', 'machine', '1.4s', '5m ago', '3'],
    ]);
    expect(target.querySelector('[data-pipeline-chart] [data-mark="failed"]')).not.toBeNull();
    expect(target.textContent).not.toContain('deepsearch');
  });

  test('a row a plugin contributes (backups) draws like any other: its catalog name, its catalog area, run time, age, runs and failure mark', async () => {
    contributed = [{ plugin: 'backups', kind: 'delivery', scope: 'plugin', session_uuid: null, session: null, project_id: null,
      project: null, conversation_id: null, family: null, trigger: null, finished_at: Date.now() / 1000 - 90, duration_ms: 350,
      runs: 6, events: 2, outcome: 'failed', error: 'capture_failed' }];
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const rows = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-row')].map((row) =>
      [...row.querySelectorAll('[data-col]')].map(shown));
    expect(rows).toContainEqual(['backups', 'conversations', '350 ms', '1m ago', '6']);
    expect(target.querySelectorAll('[data-pipeline-chart] [data-mark="failed"]')).toHaveLength(2);
    expect(target.textContent).not.toContain('pipeline.plugin_');
  });

  test('a seeded backups row (read from disk after a restart) shows its time, n/a for what was not measured, and the totals on hover', async () => {
    contributed = [{ plugin: 'backups', kind: 'delivery', scope: 'plugin', session_uuid: null, session: null, project_id: null,
      project: null, conversation_id: null, family: null, trigger: null, finished_at: Date.now() / 1000 - 600, duration_ms: null,
      runs: null, events: 0, outcome: 'ok', error: null, seeded: true, detail: { conversations: 42, size_bytes: 1572864 } }];
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const rows = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-row')].map((row) =>
      [...row.querySelectorAll('[data-col]')].map(shown));
    expect(rows).toContainEqual(['backups', 'conversations', 'n/a', '10m ago', 'n/a']);
    expect(target.querySelector('[title="42 conversations backed up, 1.5 MB on disk"]')).not.toBeNull();
    expect(target.textContent).not.toContain('NaN');
  });

  test('with no plugin contributing there is no backups row', async () => {
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(target.textContent).not.toContain('backups');
  });

  test('each row says its outcome in words, and a failure names its error, not only by the mark', async () => {
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const names = [...target.querySelectorAll('[data-pipeline-chart] .oc-rc-name')];
    expect(names.map((el) => el.querySelector('[data-outcome-words]')?.textContent?.trim())).toEqual(['ok', 'failed: KeyError']);
    // The tooltip names what the mark means, on the mark (a tooltip only says what an icon shows, #1209), never the name.
    expect(names[1]?.getAttribute('title')).toBeNull();
    expect(names[1]?.querySelector('.oc-rc-mark')?.getAttribute('title')).toBe('failed: KeyError');
  });

  test('how long ago ticks on the clock the cell holds, with no app around it and no new data', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date'] });
    pinnedNow = Date.now() / 1000;
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const age = () => shown(target.querySelectorAll('[data-pipeline-chart] .oc-table-row [data-col="ago"]')[0]!);
    expect(age()).toBe('12s ago');
    vi.advanceTimersByTime(60_000);
    await settle();
    expect(age()).toBe('1m ago');
  });

  test('a narrow widget keeps the run time, and its track is never narrower than its widest value', async () => {
    const target = put(Cell, { width: 300, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const heads = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-headcell')].map((el) => el.textContent?.trim());
    expect(heads).toEqual(['name', 'area', 'run time', 'ago']);
    const table = target.querySelector<HTMLElement>('[data-pipeline-chart] .oc-table')!;
    const tracks = table.style.getPropertyValue('--oc-table-tracks');
    const runTimeTrack = tracks.split(/ (?=minmax\()/)[2]!;
    const widest = Math.max(...[999, 59_900, 3_599_000, 359_940_000].map((ms) => runTimeWords(ms).length));
    const chars = Number(/calc\((\d+)ch \+ (\d+)px\)/.exec(runTimeTrack)?.[1]);
    const pad = Number(/calc\((\d+)ch \+ (\d+)px\)/.exec(runTimeTrack)?.[2]);
    expect(widest).toBe(7);
    expect(chars).toBeGreaterThanOrEqual(widest);
    expect(pad).toBeGreaterThanOrEqual(20);
    expect(tracks.split(/ (?=minmax\()/).slice(0, 2)).toEqual(['minmax(48px, 1.4fr)', 'minmax(48px, 1.6fr)']);
    const cell = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-row [data-col="runTime"]')].map(shown);
    expect(cell).toEqual(['4 ms', '1.4s']);
  });

  test('a very narrow widget drops the area before any figure', async () => {
    const target = put(Cell, { width: 220, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const heads = [...target.querySelectorAll('[data-pipeline-chart] .oc-table-headcell')].map((el) => el.textContent?.trim());
    expect(heads).toEqual(['name', 'run time', 'ago']);
  });

  test('running: each plugin on the key in flight, its area and how long it has run, ticking with no request', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date'] });
    const now = Date.now() / 1000;
    const area = { scope: 'session', session_uuid: 'u1', session: 'fix login', project_id: 3, project: 'carnivore', conversation: null };
    running = [
      { plugin: 'stats', kind: 'delivery', ...area, family: 'claude', trigger: 'live', started_at: now - 3, running_s: 3 },
      { plugin: 'deepsearch', kind: 'rebuild', scope: 'machine', session_uuid: null, session: null, project_id: null, project: null,
        conversation: null, family: null, trigger: 'rebuild', started_at: now - 65, running_s: 65 },
    ];
    const target = put(Cell, { width: 480, height: 400, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const section = target.querySelector('[data-rq-section="running"]')!;
    const rows = () => [...section.querySelectorAll('[data-rq-row]')].map((row) => row.textContent?.replace(/\s+/g, ' ').trim());
    expect(section.querySelector('[data-rq-count]')?.textContent).toBe('2');
    expect(rows()).toEqual(['stats fix login 3s', 'deep search rebuild machine 1m 05s']);
    vi.advanceTimersByTime(2000);
    await settle();
    expect(rows()[0]).toBe('stats fix login 5s');
    const top = target.querySelector('[data-ps="top"]')!;
    const chart = target.querySelector('[data-pipeline-chart]')!;
    expect(top.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test('queue: the server order, capped at eight with "+N more", who it waits for and how long, unnamed keys loudly', async () => {
    const now = Date.now() / 1000;
    const machine = { scope: 'machine', session_uuid: null, session: null, project_id: null, project: null, conversation: null };
    queue = {
      total: 12,
      items: [
        { plugins: [], ...machine, conversation: 'abcdef01', family: 'claude', trigger: 'live', backoff: false, marked_at: now - 4, waited_s: 4, due_at: null },
        { plugins: ['stats'], ...machine, family: 'claude', trigger: 'plugins', backoff: true, marked_at: now - 60, waited_s: 60, due_at: now + 30.5 },
        ...Array.from({ length: 8 }, (_, i) => ({ plugins: [], ...machine, family: 'claude', trigger: 'plugins', backoff: false,
          marked_at: now - 100 - i, waited_s: 100 + i, due_at: null })),
      ],
    };
    const target = put(Cell, { width: 480, height: 400, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    const section = target.querySelector('[data-rq-section="queue"]')!;
    const rows = [...section.querySelectorAll('[data-rq-row]')];
    expect(rows).toHaveLength(8);
    expect(section.querySelector('[data-rq-count]')?.textContent).toBe('12');
    expect(section.querySelector('[data-rq-more]')?.textContent).toBe('+4 more');
    const text = (row: Element) => [...row.children].map((el) => el.textContent?.trim());
    expect(text(rows[0]!)).toEqual(['all plugins', 'abcdef01', 'waited 4s']);
    expect(text(rows[1]!)).toEqual(['stats', 'machine', 'retry in 0m 30s']);
    expect(rows[1]?.getAttribute('data-tone')).toBe('wait');
    expect(target.querySelector('[data-rq-section="running"] [data-rq-none]')?.textContent).toBe('nothing running');
  });

  test('an idle engine says nothing is running or waiting', async () => {
    const target = put(Cell, { width: 480, height: 400, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect([...target.querySelectorAll('[data-rq-none]')].map((el) => el.textContent)).toEqual(['nothing running', 'nothing waiting']);
    expect(target.querySelector('[data-rq-more]')).toBeNull();
  });

  test('the widget and the settings panel open together on one read, not two', async () => {
    put(Cell, { width: 420, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    const panel = put(PipelineStatusPanel, {});
    await settle();
    expect(reads.filter((path) => path === '/pipeline/status')).toHaveLength(1);
    expect(panel.querySelector('[data-ps="line"]')).not.toBeNull();
  });

  test('closing the last view stops the shared read, and the next one starts a fresh one', async () => {
    put(Cell, { width: 420, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    for (const app of apps.splice(0)) unmount(app);
    reads.length = 0;
    put(Cell, { width: 420, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(reads.filter((path) => path === '/pipeline/status')).toHaveLength(1);
  });

  const backupsRow = (outcome: string) => ({ plugin: 'backups', kind: 'delivery', scope: 'plugin', session_uuid: null, session: null,
    project_id: null, project: null, conversation_id: null, family: null, trigger: null, finished_at: Date.now() / 1000 - 60,
    duration_ms: 350, runs: 6, events: 1, outcome, error: outcome === 'failed' ? 'OSError' : null });
  const squareBtn = (target: Element, id: string) => target.querySelector(`[data-ps-square="${id}"] button`) as HTMLButtonElement;
  const chartNames = (target: Element) => [...target.querySelectorAll('[data-pipeline-chart] .oc-rc-name-text')].map((el) => el.textContent?.trim());

  test('a backups square appears only while the backups row is present, failing when its last run failed', async () => {
    const off = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(off.querySelector('[data-ps-square="backups"]')).toBeNull();
    unmount(apps.pop()!);
    await settle();
    contributed = [backupsRow('ok')];
    const on = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(squareBtn(on, 'backups').getAttribute('data-state')).toBe('ok');
    unmount(apps.pop()!);
    await settle();
    contributed = [backupsRow('failed')];
    const bad = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(squareBtn(bad, 'backups').getAttribute('data-state')).toBe('failing');
  });

  test('clicking a square filters the chart to that plugin; again clears it; another switches; aria-pressed follows', async () => {
    contributed = [backupsRow('ok')];
    const target = put(Cell, { width: 480, height: 300, meta: META['pipeline'], instance: 'pipeline', page: 'home' });
    await settle();
    expect(chartNames(target)).toEqual(['deep search', 'stats', 'backups']);
    expect(squareBtn(target, 'stats').getAttribute('aria-pressed')).toBe('false');
    squareBtn(target, 'stats').click(); flushSync();
    expect(chartNames(target)).toEqual(['stats']);
    expect(squareBtn(target, 'stats').getAttribute('aria-pressed')).toBe('true');
    squareBtn(target, 'backups').click(); flushSync();
    expect(chartNames(target)).toEqual(['backups']);
    expect(squareBtn(target, 'stats').getAttribute('aria-pressed')).toBe('false');
    squareBtn(target, 'backups').click(); flushSync();
    expect(chartNames(target)).toEqual(['deep search', 'stats', 'backups']);
    expect(squareBtn(target, 'backups').getAttribute('aria-pressed')).toBe('false');
  });

  test('the settings panel squares are not filter toggles', async () => {
    const target = put(PipelineStatusPanel, { compact: true });
    await settle();
    expect(squareBtn(target, 'stats').hasAttribute('aria-pressed')).toBe(false);
  });
});
