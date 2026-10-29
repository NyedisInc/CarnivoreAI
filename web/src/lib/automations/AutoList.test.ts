/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { readFileSync } from 'node:fs';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(),
  listTargets: vi.fn(),
  getRunCounts: vi.fn(),
  listRuns: vi.fn(),
  listProjectChoices: vi.fn(),
  listSessionRecords: vi.fn(),
  updateAutomation: vi.fn(),
  runAutomationNow: vi.fn(),
  createAutomation: vi.fn(),
  deleteAutomation: vi.fn(),
  getRun: vi.fn(),
  listFeed: vi.fn(),
}));
vi.mock('./api', () => stub);
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import AutoList from './AutoList.svelte';
import { data } from './page-store.svelte';
import { view } from './list-state.svelte';

const css = readFileSync(`${process.cwd()}/src/lib/automations/auto-list.css`, 'utf8');
const NOW = 1_800_000_000;
const run = (n: number, status: string, over: Record<string, unknown> = {}) => ({
  run_id: `r${n}`, number: n, status, reason: null, trigger: 'schedule', attempt: null, slot_at: NOW - 3600 * n, started_at: NOW - 3600 * n,
  ended_at: NOW - 3600 * n + 2, skip_count: null, report_bytes: 10, output_empty: false, ...over,
});
const base = {
  trigger: { cron: '0 7 * * 1', timezone: 'local' }, delivery: { notify: true, notify_on: null }, revision: 1, last_run: null, next_fire_at: null,
  description: '', project_id: null, enabled: true, median_took_s: 2, newest_output_empty: false, run_count: 1, newest_number: 1, spends: false,
  files_under: { session_uuid: null, project_id: null }, target: { kind: 'command', command: '/usr/bin/git pull', project_id: null },
};
const auto = (id: string, name: string, recent: unknown[], over: Record<string, unknown> = {}) => ({ ...base, automation_id: id, name, recent, ...over });
const automations = () => [
  auto('aut_a', 'alpha ok', [run(3, 'succeeded'), run(2, 'succeeded')], { next_fire_at: NOW + 600 }),
  auto('aut_b', 'bravo off', [run(1, 'succeeded')], { enabled: false }),
  auto('aut_c', 'charlie empty', [run(1, 'succeeded', { output_empty: true })], { newest_output_empty: true }),
  auto('aut_d', 'delta skipped', [run(1, 'skipped')]),
  auto('aut_e', 'echo failed', [run(1, 'failed')], { description: 'weekly cost report', project_id: 7 }),
  auto('aut_f', 'foxtrot waiting', [run(1, 'waiting_on_you')]),
];
const counts = (failedIds: string[]) => ({
  now: NOW, hosts: [], has_unrecorded_host: false, next_change_at: null,
  counters: Object.fromEntries(
    ['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you'].map((id) => [
      id, { count: id === 'failed_24h' ? failedIds.length : 0, automation_ids: id === 'failed_24h' ? failedIds : [] },
    ]),
  ),
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const ids = () => [...document.querySelectorAll('[data-automation]')].map((r) => r.getAttribute('data-automation'));
const mountList = async () => {
  app = mount(AutoList, { target: document.body });
  await settle();
};
const type = async (el: HTMLInputElement, value: string) => {
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
};
const motion = (reduce: boolean) =>
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: reduce && query.includes('reduce'), media: query, addEventListener() {}, removeEventListener() {} }));

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.listRuns.mockResolvedValue({ runs: [] });
  stub.listAutomations.mockRejectedValue(new Error('server down'));
  stub.listTargets.mockResolvedValue({ kinds: [], commands: [], recipes: [] });
  stub.getRunCounts.mockRejectedValue(new Error('no route'));
  motion(false);
  data.status = 'ready';
  data.error = '';
  data.automations = automations() as never;
  data.tz = 'UTC';
  data.now = NOW;
  data.paused = false;
  data.counts = null;
  data.pressed = {};
  data.projects = [{ id: 7, name: 'site', folder: '/x/site' }] as never;
  data.selectedId = null;
  data.paneOpen = false;
  data.notice = '';
  view.q = '';
  view.pills = [];
  view.sort = { k: 'light', d: 1 };
  view.dens = 'comfortable';
  view.confirmId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

function topLevel(text: string): string {
  let out = '';
  let depth = 0;
  let inAt = false;
  const src = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/@layer components\s*\{/, '').replace(/\}\s*$/, '');
  for (let i = 0; i < src.length; i++) {
    const c = src[i]!;
    if (depth === 0 && c === '@') inAt = true;
    if (!inAt) out += c;
    if (c === '{') depth++;
    if (c === '}') {
      depth--;
      if (depth === 0 && inAt) inAt = false;
    }
  }
  return out;
}
function tiers(text: string): { min: number; body: string }[] {
  const src = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const found: { min: number; body: string }[] = [];
  for (const m of src.matchAll(/@container ap-list \(min-width: (\d+)px\)\s*\{/g)) {
    let depth = 1;
    let i = m.index! + m[0].length;
    const start = i;
    while (depth && i < src.length) depth += src[i] === '{' ? 1 : src[i] === '}' ? -1 : 0, i++;
    found.push({ min: Number(m[1]), body: src.slice(start, i - 1) });
  }
  return found;
}
function layoutAt(width: number): { cols: string[]; tracks: number } {
  const shown = new Set(['light', 'name', 'last', 'act']);
  const displayed = (body: string) => [...body.matchAll(/([^{}]+)\{[^{}]*\bdisplay:\s*(?!none)[a-z]+[^{}]*\}/g)].flatMap((m) => [...m[1]!.matchAll(/\.ap-c-(\w+)/g)].map((x) => x[1]!));
  const hidden = [...topLevel(css).matchAll(/([^{}]+)\{[^{}]*\bdisplay:\s*none[^{}]*\}/g)].flatMap((m) => [...m[1]!.matchAll(/\.ap-c-(\w+)/g)].map((x) => x[1]!));
  for (const c of ['strip', 'rate', 'on', 'next', 'med']) expect(hidden).toContain(c);
  let template = /\.ap-row[^{}]*\{[^{}]*grid-template-columns:\s*([^;}]+)/.exec(topLevel(css))![1]!;
  for (const tier of tiers(css).sort((a, b) => a.min - b.min)) {
    if (tier.min > width) continue;
    displayed(tier.body).forEach((c) => shown.add(c));
    template = /grid-template-columns:\s*([^;}]+)/.exec(tier.body)![1]!;
  }
  let flat = template.trim();
  while (/\([^()]*\)/.test(flat)) flat = flat.replace(/\([^()]*\)/g, 'X');
  return { cols: [...shown], tracks: flat.split(/\s+/).length };
}

test('columns follow the container width, one grid track per visible column', () => {
  const at = (w: number) => layoutAt(w);
  expect(at(856).cols.sort()).toEqual(['act', 'last', 'light', 'name', 'rate', 'strip']);
  expect(at(1062).cols.sort()).toEqual(['act', 'last', 'light', 'name', 'on', 'rate', 'strip']);
  expect(at(1136).cols.sort()).toEqual(['act', 'last', 'light', 'med', 'name', 'next', 'on', 'rate', 'strip']);
  expect(at(1416).cols.sort()).toEqual(['act', 'last', 'light', 'med', 'name', 'next', 'on', 'rate', 'strip']);
  for (const w of [856, 1062, 1136, 1416]) expect(at(w).tracks).toBe(at(w).cols.length);
  expect(at(600).cols.length).toBe(4);
});

test('one row per automation, tags in the fixed rule order, needs attention first, and an unscheduled row says none', async () => {
  await mountList();
  expect(ids()).toEqual(['aut_f', 'aut_e', 'aut_d', 'aut_c', 'aut_b', 'aut_a']);
  const tags = [...document.querySelectorAll('[data-attention-tag]')].map((el) => el.textContent);
  expect(tags).toEqual(['waiting on you', 'last run failed', 'skipped lately', 'newest output empty', 'switched off']);
  expect(q('[data-automation="aut_a"] [data-automation-next]').textContent).toContain('in 10 min');
  expect(q('[data-automation="aut_f"] [data-automation-next]').textContent).toContain('none');
  expect(q('[data-automation="aut_b"] [data-automation-next]').textContent).toContain('off');
  q('[data-auto-dir]').click();
  await settle();
  expect(ids()[0]).toBe('aut_a');
  expect(document.querySelector('[role="columnheader"][aria-sort]')!.getAttribute('aria-sort')).toBe('descending');
});

test('a pressed counter, the filter pills and the search all narrow the list, and search reaches what a row is for', async () => {
  data.counts = counts(['aut_e', 'aut_d']) as never;
  data.pressed = { failed_24h: true };
  await mountList();
  expect(ids()).toEqual(['aut_e', 'aut_d']);
  const add = q<HTMLSelectElement>('[data-auto-addf]');
  add.value = 'status|failed';
  add.dispatchEvent(new Event('change', { bubbles: true }));
  await settle();
  expect(ids()).toEqual(['aut_e']);
  expect(document.querySelectorAll('[data-auto-pill]').length).toBe(1);
  await type(q<HTMLInputElement>('[data-auto-find]'), 'zzz');
  expect(ids()).toEqual([]);
  expect(q('[data-auto-list]').textContent).toContain('no automation matches these filters.');
  expect(q('[data-auto-count]').textContent).toContain('0 of 6');
  q('[data-auto-clear]').click();
  await settle();
  expect(ids().length).toBe(6);
  expect(data.pressed.failed_24h).toBeFalsy();
  await type(q<HTMLInputElement>('[data-auto-find]'), 'weekly cost');
  expect(ids()).toEqual(['aut_e']);
  await type(q<HTMLInputElement>('[data-auto-find]'), 'site');
  expect(ids()).toEqual(['aut_e']);
});

test('arrow keys walk the table, enter opens the pane, and typing in find keeps focus', async () => {
  await mountList();
  const grid = q('[data-auto-list]');
  grid.focus();
  grid.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  await settle();
  expect(data.selectedId).toBe('aut_f');
  grid.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  await settle();
  expect(data.selectedId).toBe('aut_e');
  expect(q('[data-automation="aut_e"]').getAttribute('aria-selected')).toBe('true');
  expect(data.paneOpen).toBe(false);
  grid.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await settle();
  expect(data.paneOpen).toBe(true);
  const find = q<HTMLInputElement>('[data-auto-find]');
  find.focus();
  await type(find, 'ech');
  expect(document.activeElement).toBe(find);
  expect(q<HTMLInputElement>('[data-auto-find]')).toBe(find);
  expect(q('[data-auto-count]').textContent).toContain('1 of 6');
});

test('a failed read is an alert with try again and no toolbar; try again reads the list again', async () => {
  data.status = 'error';
  data.error = 'server down';
  await mountList();
  expect(q('[role="alert"]').textContent).toContain('server down');
  expect(q('[data-list-retry]').textContent).toBe('try again');
  expect(document.querySelector('[data-auto-toolbar]')).toBeNull();
  q('[data-list-retry]').click();
  await settle();
  expect(stub.listAutomations).toHaveBeenCalled();
});

test('the empty page offers a new automation and three templates and has no header row', async () => {
  data.automations = [];
  await mountList();
  expect(q('[data-auto-empty]').textContent).toContain('no automations yet');
  expect(document.querySelectorAll('[data-tpl]').length).toBe(3);
  expect(document.querySelector('[role="columnheader"]')).toBeNull();
});

test('a landed run shifts the strip one mark only when motion is allowed', async () => {
  motion(true);
  await mountList();
  data.automations = [auto('aut_a', 'alpha ok', [run(4, 'succeeded'), run(3, 'succeeded')]), ...(automations().slice(1) as never[])] as never;
  await settle();
  expect(document.querySelector('[data-shift]')).toBeNull();
  unmount(app!);
  document.body.innerHTML = '';
  data.automations = automations() as never;
  motion(false);
  await mountList();
  data.automations = [auto('aut_a', 'alpha ok', [run(4, 'succeeded'), run(3, 'succeeded')]), ...(automations().slice(1) as never[])] as never;
  await settle();
  expect(q('[data-automation="aut_a"] [data-strip-in]').hasAttribute('data-shift')).toBe(true);
});

test('the newest run line follows the selected row', async () => {
  await mountList();
  expect(q('[data-auto-preview]').textContent).toContain('select an automation to read its newest run here.');
  q('[data-automation="aut_a"]').click();
  await settle();
  expect(data.selectedId).toBe('aut_a');
  expect(data.paneOpen).toBe(true);
  expect(q('[data-auto-preview]').textContent).toContain('#3');
});
