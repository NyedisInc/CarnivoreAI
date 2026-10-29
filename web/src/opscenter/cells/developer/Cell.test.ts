/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const NOW = Math.floor(Date.now() / 1000);
let runs: Record<string, unknown>[] = [];
let automations: Record<string, unknown>[] = [];
const reads: string[] = [];
let taskManagerAnswer: 'items' | 'hang' | 'fail' = 'items';
let automationsAnswer: 'rows' | 'fail' = 'rows';
let projects: Record<string, unknown>[] = [];

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    reads.push(path);
    if (path === '/automations' || path.startsWith('/automations/runs')) {
      if (automationsAnswer === 'fail') throw new Error('automations down');
      return path === '/automations' ? { automations } : { runs };
    }
    if (path === '/projects') return projects;
    if (path === '/cplugs/huddle/scheduled') {
      if (taskManagerAnswer === 'hang') return new Promise(() => {});
      if (taskManagerAnswer === 'fail') throw new Error('huddle down');
      return { schedules: [{ list: '3', item: 7, title: 'sweep the board', next_fire: new Date((NOW + 600) * 1000).toISOString(), paused: false, state: 'pending', pings: { project: 'carnivore', session_key: null } }] };
    }
    if (path === '/pipeline/status') return { state: 'caught_up', lag: { files: 0, seconds: 0 }, last_delivery_at: null, stalled_since: null, rebuilding: [], plugins: {} };
    return null;
  },
}));

vi.mock('../../api/events.svelte', () => ({ subscribe: () => () => {} }));

import Cell from './Cell.svelte';
import { widestChars } from '../../lib/run-chart';
import { MONITORS } from './meta';
import { META } from '../../engine/meta';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { resourcePush } from '../../../lib/resource-push/boot';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';

globalThis.ResizeObserver ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} } as unknown as typeof ResizeObserver;

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

function run(id: string, name: string, status: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return { run_id: id, automation_id: 'a1', automation_name: name, status, started_at: NOW - 120, ended_at: NOW - 60, ...over };
}

beforeEach(() => {
  reads.length = 0;
  taskManagerAnswer = 'items';
  automationsAnswer = 'rows';
  projects = [{ id: 3, name: 'carnivore', path: '/p' }];
  globalThis.localStorage?.clear();
  cplugEnablement.enabled = {};
  automations = [
    { automation_id: 'a1', name: 'nightly backup', enabled: true, next_fire_at: NOW + 3600, project_id: 3, target: { kind: 'recipe' },
      last_run: run('r2', 'nightly backup', 'succeeded', { trigger: 'run_now', notes: { by: { kind: 'mcp', tmux: 'carnivore_fix', name: 'fix login' } } }) },
    { automation_id: 'a2', name: 'weekly audit', enabled: false, next_fire_at: null, project_id: null, target: { kind: 'command' },
      last_run: run('r3', 'weekly audit', 'failed', { trigger: 'schedule' }) },
    { automation_id: 'a3', name: 'never run', enabled: false, next_fire_at: null, project_id: null, target: { kind: 'recipe' }, last_run: null },
  ];
  runs = [
    run('r1', 'nightly backup', 'running', { ended_at: null }),
    run('r2', 'nightly backup', 'succeeded'),
    run('r3', 'weekly audit', 'failed'),
  ];
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function render(width = 600): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(Cell, { target, props: { width, height: 300, meta: META['developer'], instance: 'developer', page: 'home' } as never }));
  await settle();
  return target;
}

describe('the developer widget tabs', () => {
  test('one tab per monitor entry, the pipeline cell shown first', async () => {
    const target = await render();
    const tabs = [...target.querySelectorAll('[role="tab"]')].map((el) => el.textContent?.trim());
    expect(tabs).toEqual(['pipeline', 'scheduled', 'sent', 'log']);
    expect(MONITORS.map((m) => m.id)).toEqual(['pipeline', 'scheduled', 'sent', 'log']);
    expect(target.querySelector('[data-pipeline-cell]')).not.toBeNull();
    expect(target.querySelector('[data-scheduled-monitor]')).toBeNull();
    expect(reads).not.toContain('/automations');
  });

  test('the chosen tab is declared widget state: the older key is still read, a pick is kept under the declared one', async () => {
    globalThis.localStorage?.setItem('carnivore.tabs.developer-widget', 'scheduled');
    const target = await render();
    expect(target.querySelector('[data-developer-panel="scheduled"]')).not.toBeNull();
    (target.querySelector('[data-tab="log"]') as HTMLElement).click();
    await settle();
    expect(target.querySelector('[data-developer-panel="log"]')).not.toBeNull();
    expect(globalThis.localStorage?.getItem('carnivore.core.developer.tab')).toBe('log');
  });

  test('every monitor wears the pipeline tab layout: a .oc-rc root that opens with a hairline strip', async () => {
    const target = await render();
    for (const monitor of MONITORS) {
      (target.querySelector(`[data-tab="${monitor.id}"]`) as HTMLElement).click();
      await settle();
      const root = target.querySelector(`[data-developer-panel="${monitor.id}"] .oc-rc`);
      expect(root, monitor.id).not.toBeNull();
      const first = root?.firstElementChild;
      expect(first?.matches('.oc-rc-bar') || first?.querySelector('.ps-top') !== null || first?.classList.contains('ps-top'), monitor.id).toBe(true);
    }
  });

  async function scheduled(): Promise<HTMLElement> {
    const target = await render();
    (target.querySelector('[data-tab="scheduled"]') as HTMLElement).click();
    await settle();
    return target;
  }

  function chart(target: HTMLElement): string[][] {
    return [...target.querySelectorAll('[data-scheduled-chart] .oc-table-row')].map((row) =>
      [...row.querySelectorAll('[data-col]')].map((cell) => {
        const copy = cell.cloneNode(true) as Element;
        for (const hidden of copy.querySelectorAll('[data-outcome-words]')) hidden.remove();
        return copy.textContent?.trim() ?? '';
      }));
  }

  async function pickScope(target: HTMLElement, scope: string): Promise<void> {
    (target.querySelector(`[data-scope="${scope}"]`) as HTMLElement).click();
    await settle();
  }

  test('the scheduled tab is a chart: name, what ran it, area, run time, how long ago and the next run', async () => {
    const target = await scheduled();
    expect(target.querySelector('[data-pipeline-cell]')).toBeNull();
    const heads = [...target.querySelectorAll('[data-scheduled-chart] .oc-table-headcell')].map((el) => el.textContent?.trim());
    expect(heads).toEqual(['name', 'ran by', 'area', 'run time', 'ago', 'next']);
    const rows = chart(target);
    expect(rows[0]?.slice(0, 5)).toEqual(['nightly backup', 'run now by fix login', 'carnivore', '1m 00s', '1m ago']);
    expect(rows[0]?.[5]).toMatch(/^in (59m 5\ds|1h 00m)$/);
    expect(rows[1]).toEqual(['weekly audit', 'schedule', 'machine', '1m 00s', '1m ago', '']);
    expect(rows.map((r) => r[0])).not.toContain('never run');
    expect(target.querySelector('[data-scheduled-chart] [data-mark="error"]')).not.toBeNull();
  });

  test('a failed row says so in words, for a screen reader and on hover, not only by the mark', async () => {
    const target = await scheduled();
    const failed = [...target.querySelectorAll('[data-scheduled-chart] .oc-rc-name')].find((el) => el.textContent?.includes('weekly audit'));
    expect(failed?.querySelector('[data-outcome-words]')?.textContent?.trim()).toBe('failed');
    // The tooltip names what the mark means, on the mark (a tooltip only says what an icon shows, #1209), never the name.
    expect(failed?.getAttribute('title')).toBeNull();
    expect(failed?.querySelector('.oc-rc-mark')?.getAttribute('title')).toBe('failed');
  });

  test('the sessions view waits on the huddle read, not the automations read', async () => {
    taskManagerAnswer = 'hang';
    const target = await scheduled();
    await pickScope(target, 'sessions');
    expect(target.querySelector('[data-scheduled-monitor]')?.getAttribute('data-view')).toBe('loading');
    expect(target.querySelector('[data-scheduled-none]')).toBeNull();
  });

  test('a failed huddle read in the sessions view says it could not be read', async () => {
    taskManagerAnswer = 'fail';
    const target = await scheduled();
    await pickScope(target, 'sessions');
    expect(target.querySelector('[data-scheduled-monitor]')?.getAttribute('data-view')).toBe('unknown');
    expect(target.querySelector('[data-scheduled-note="unknown"]')?.textContent?.trim()).toBe('scheduled runs could not be read');
    expect(target.querySelector('[data-scheduled-none]')).toBeNull();
  });

  test('a failed automations read keeps the huddle rows that did load, and says what could not be read', async () => {
    automationsAnswer = 'fail';
    const target = await scheduled();
    expect(target.querySelector('[data-scope="both"]')?.getAttribute('aria-checked')).toBe('true');
    expect(chart(target).map((r) => r[0])).toEqual(['sweep the board']);
    expect(target.querySelector('[data-scheduled-note="unknown"]')).not.toBeNull();
    await pickScope(target, 'sessions');
    expect(target.querySelector('[data-scheduled-note="unknown"]')).toBeNull();
    expect(chart(target).map((r) => r[0])).toEqual(['sweep the board']);
  });

  test('a projects frame re-reads the names, and an id /projects never answers costs no read per push', async () => {
    globalThis.localStorage?.setItem('carnivore.tabs.scope.developer-scheduled', 'global');
    automations = [...automations, { automation_id: 'a7', name: 'archived job', enabled: true, next_fire_at: NOW + 60, project_id: 99,
      target: { kind: 'recipe' }, last_run: null }];
    const target = await scheduled();
    resourcePush().store.hello({ resource_topics: ['automations', 'automation_runs', 'projects'] });
    await settle();
    const projectReads = () => reads.filter((p) => p === '/projects').length;
    const before = projectReads();
    resourcePush().store.frame({ topics: ['automation_runs'] });
    await settle();
    expect(projectReads()).toBe(before);
    projects = [{ id: 3, name: 'carnivore renamed', path: '/p' }];
    resourcePush().store.frame({ topics: ['projects'] });
    await settle();
    expect(projectReads()).toBe(before + 1);
    expect(chart(target)[0]?.[2]).toBe('carnivore renamed');
  });

  test('a narrow widget keeps the run time, and its track is never narrower than its widest value', async () => {
    for (const [width, want] of [[400, ['name', 'ran by', 'run time', 'ago', 'next']], [300, ['name', 'run time', 'ago', 'next']]] as const) {
      const target = await render(width);
      (target.querySelector('[data-tab="scheduled"]') as HTMLElement).click();
      await settle();
      const heads = [...target.querySelectorAll('[data-scheduled-chart] .oc-table-headcell')].map((el) => el.textContent?.trim());
      expect(heads).toEqual(want);
      const tracks = target.querySelector<HTMLElement>('[data-scheduled-chart] .oc-table')!.style.getPropertyValue('--oc-table-tracks');
      const runTimeTrack = tracks.split(/ (?=minmax\()/)[want.indexOf('run time')]!;
      const [, chars, pad] = /calc\((\d+)ch \+ (\d+)px\)/.exec(runTimeTrack) ?? [];
      expect(Number(chars)).toBeGreaterThanOrEqual(widestChars('runTime'));
      expect(Number(pad)).toBeGreaterThanOrEqual(20);
      for (const app of apps.splice(0)) unmount(app);
      document.body.innerHTML = '';
    }
  });

  test('the filter: both by default, sessions shows the huddle items, global the automations only, remembered', async () => {
    let target = await scheduled();
    expect(target.querySelector('[data-scope="both"]')?.getAttribute('aria-checked')).toBe('true');
    expect(chart(target).map((r) => r[0])).toEqual(['nightly backup', 'weekly audit', 'sweep the board']);
    (target.querySelector('[data-scope="sessions"]') as HTMLElement).click();
    await settle();
    const sessions = chart(target);
    expect(sessions.map((r) => r.slice(0, 5))).toEqual([['sweep the board', 'schedule', 'carnivore', '', '']]);
    expect(sessions[0]?.[5]).toMatch(/^in (9m 5\ds|10m 00s)$/);
    (target.querySelector('[data-scope="global"]') as HTMLElement).click();
    await settle();
    expect(chart(target).map((r) => r[0])).toEqual(['nightly backup', 'weekly audit']);
    for (const app of apps.splice(0)) unmount(app);
    document.body.innerHTML = '';
    target = await render();
    expect(target.querySelector('[data-scheduled-monitor]')?.getAttribute('data-scheduled-scope')).toBe('global');
  });

  test('with the huddle plugin off, sessions says so in a plain line and its route is never read', async () => {
    cplugEnablement.enabled = { huddle: false };
    const target = await scheduled();
    (target.querySelector('[data-scope="sessions"]') as HTMLElement).click();
    await settle();
    expect(target.querySelector('[data-scheduled-chart]')).toBeNull();
    expect(target.querySelector('[data-scheduled-huddle-off]')?.textContent?.trim()).toBe('the task manager plugin is off');
    expect(reads).not.toContain('/cplugs/huddle/scheduled');
  });

  test('the global filter never reads the huddle route', async () => {
    globalThis.localStorage?.setItem('carnivore.tabs.scope.developer-scheduled', 'global');
    await scheduled();
    expect(reads).not.toContain('/cplugs/huddle/scheduled');
  });

  test('the chosen tab is remembered across a remount', async () => {
    let target = await render();
    (target.querySelector('[data-tab="scheduled"]') as HTMLElement).click();
    await settle();
    for (const app of apps.splice(0)) unmount(app);
    document.body.innerHTML = '';
    target = await render();
    expect(target.querySelector('[data-scheduled-monitor]')).not.toBeNull();
  });

  test('a pushed automation_runs frame re-reads the runs and the new row appears', async () => {
    const target = await render();
    (target.querySelector('[data-tab="scheduled"]') as HTMLElement).click();
    await settle();
    resourcePush().store.hello({ resource_topics: ['automations', 'automation_runs'] });
    await settle();
    const before = reads.filter((p) => p.startsWith('/automations/runs')).length;
    automations = [...automations, { automation_id: 'a9', name: 'late task', enabled: true, next_fire_at: null, project_id: null,
      target: { kind: 'recipe' }, last_run: run('r9', 'late task', 'failed', { trigger: 'retry', ended_at: NOW - 5 }) }];
    resourcePush().store.frame({ topics: ['automation_runs'] });
    await settle();
    expect(reads.filter((p) => p.startsWith('/automations/runs')).length).toBe(before + 1);
    expect(chart(target)[0]?.slice(0, 2)).toEqual(['late task', 'retry']);
  });

  function section(target: HTMLElement, id: 'running' | 'queue'): string[][] {
    return [...target.querySelectorAll(`[data-rq-section="${id}"] [data-rq-row]`)].map((row) =>
      [...row.children].map((el) => el.textContent?.trim() ?? ''));
  }

  test('running and queue sit over the chart: the run in progress with what ran it, then the next fires soonest first', async () => {
    runs = [run('r1', 'nightly backup', 'running', { ended_at: null, trigger: 'schedule' }), ...runs.slice(1)];
    const target = await scheduled();
    const running = section(target, 'running');
    expect(running).toHaveLength(1);
    expect(running[0]?.slice(0, 2)).toEqual(['nightly backup', 'schedule']);
    expect(running[0]?.[2]).toMatch(/^2m 0\ds$/);
    const queue = section(target, 'queue');
    expect(queue.map((row) => row.slice(0, 2))).toEqual([['sweep the board', 'carnivore'], ['nightly backup', 'carnivore']]);
    expect(queue.every((row) => /^in \d+[hm] \d+[ms]$/.test(row[2] ?? ''))).toBe(true);
    const sections = target.querySelector('[data-run-queue]')!;
    const chartEl = target.querySelector('[data-scheduled-chart]')!;
    expect(sections.compareDocumentPosition(chartEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test('the filter applies to running and queue: sessions shows only the huddle fires, global only the automations', async () => {
    const target = await scheduled();
    await pickScope(target, 'sessions');
    expect(section(target, 'running')).toEqual([]);
    expect(target.querySelector('[data-rq-section="running"] [data-rq-none]')?.textContent).toBe('nothing running');
    expect(section(target, 'queue').map((row) => row[0])).toEqual(['sweep the board']);
    await pickScope(target, 'global');
    expect(section(target, 'running').map((row) => row[0])).toEqual(['nightly backup']);
    expect(section(target, 'queue').map((row) => row[0])).toEqual(['nightly backup']);
  });

  test('the queue draws eight fires and counts the rest', async () => {
    automations = Array.from({ length: 11 }, (_, i) => ({ automation_id: `q${i}`, name: `task ${i}`, enabled: true,
      next_fire_at: NOW + 60 * (i + 1), project_id: null, target: { kind: 'recipe' }, last_run: null }));
    runs = [];
    globalThis.localStorage?.setItem('carnivore.tabs.scope.developer-scheduled', 'global');
    const target = await scheduled();
    expect(section(target, 'queue').map((row) => row[0])).toEqual(Array.from({ length: 8 }, (_, i) => `task ${i}`));
    expect(target.querySelector('[data-rq-section="queue"] [data-rq-more]')?.textContent).toBe('+3 more');
    expect(target.querySelector('[data-rq-section="queue"] [data-rq-count]')?.textContent).toBe('11');
  });
});
