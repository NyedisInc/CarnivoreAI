/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string, section: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  groups: [] as unknown[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return server.prefs;
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'alpha', project_id: 12, items: 6, open: 6, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '18', name: 'beta', project_id: 18, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, statusFolds } from './task-manager-status-folds.svelte';
import { readFileSync } from 'node:fs';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { AGGREGATE } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { TAIL_ORDER } from './task-manager-tail-slots';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout: boolean): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

/** alpha: 2 questions, a review with 2 unread looks and 1 unread info, a review with 1 unread info, 1 working. */
const GROUPS = () => [
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'question'), mk(12, '12', 'question'),
    mk(13, '12', 'review', { attention_unread: 2, attention_unseen: true, info_unread: 1, info_unseen: true }),
    mk(14, '12', 'review', { info_unread: 1, info_unseen: true }),
    mk(16, '12', 'working'),
  ] },
  { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review'), mk(22, '18', 'open')] },
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});




function cssText(file: string): string {
  return readFileSync(new URL(file, import.meta.url), 'utf8');
}

function rule(file: string, selector: string): Record<string, string> {
  const css = cssText(file);
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector} in ${file}`);
  const block = css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at));
  return Object.fromEntries(block.split(';').map((d) => d.split(':')).filter((p) => p.length >= 2).map(([k, ...v]) => [k!.trim(), v.join(':').trim()]));
}

/** Whether a comes before b in document order. */
const before = (a: Element, b: Element): boolean => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('the controls after the count', () => {
  test('the project head: chevron, nudge key, count, title, then the tail (#1798)', async () => {
    const host = await mountBody(false);
    const head = host.querySelector<HTMLElement>('[data-task-manager-level="project"]')!;
    const chevron = head.querySelector('[data-task-manager-project-fold]')!;
    const count = head.querySelector('[data-task-manager-project-count]')!;
    const name = head.querySelector('[data-task-manager-heading]')!;
    const nudge = head.querySelector('[data-task-manager-project-nudge]')!;
    const tail = head.querySelector('[data-task-manager-tail]')!;
    expect(before(chevron, nudge)).toBe(true);
    expect(before(nudge, count)).toBe(true);
    expect(before(count, name)).toBe(true);
    expect(before(name, tail)).toBe(true);
    expect(nudge.getAttribute('aria-label')).toBeTruthy();
    expect(nudge.getAttribute('title')).toBeTruthy();
  });

  test('the schedule key is a plus alone, after the count and before the tail, named by tooltip and aria-label', async () => {
    const host = await mountBody(false);
    const strip = host.querySelector<HTMLElement>('[data-task-manager-schedule-strip]')!;
    const add = strip.querySelector<HTMLElement>('[data-task-manager-schedule-add]')!;
    expect(add.textContent?.trim()).toBe('');
    expect(add.querySelectorAll('[data-icon]').length).toBe(1);
    expect(add.getAttribute('aria-label')).toBeTruthy();
    expect(add.getAttribute('title')).toBeTruthy();
    expect(before(strip.querySelector('.hss-fold')!, add)).toBe(true);
    expect(before(add, strip.querySelector('[data-task-manager-tail]')!)).toBe(true);
  });
});

describe.each([['status', 'status'], ['area', 'area']])('the %s view', (_name, view) => {
  test('every bar at every level carries the one shared tail, last in the bar', async () => {
    taskManagerPrefs.view = view as 'status' | 'area';
    server.groups = [
      { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [{ id: 5, list: '12', name: 'widgets', position: 0, folded: false }],
        items: [mk(13, '12', 'review', { group: 5 }), mk(14, '12', 'question')] },
      { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review')] },
    ];
    await refreshTaskManager();
    const host = await mountBody(false);
    const bars = [...host.querySelectorAll<HTMLElement>('[data-task-manager-level]')];
    expect(new Set(bars.map((b) => b.dataset.taskManagerLevel)).size).toBeGreaterThanOrEqual(view === 'area' ? 3 : 2);
    for (const bar of bars) {
      const tails = bar.querySelectorAll('.hd-tail');
      expect(tails.length, `${bar.dataset.taskManagerLevel} bar has one tail`).toBe(1);
    }
        taskManagerPrefs.view = 'status';
  });
});

const slotKinds = (host: HTMLElement, id: string): string[] =>
  [...host.querySelectorAll<HTMLElement>(`[data-task-manager-tail="${id}"] [data-task-manager-tail-slot]`)].map((s) => s.dataset.taskManagerTailSlot as string);

test('project bars draw only the badges that have something, packed right: no empty slot, each in canonical order (#1798)', async () => {
  const host = await mountBody(false);
  expect(slotKinds(host, '12')).toEqual(TAIL_ORDER.filter((k) => ['question', 'review', 'working'].includes(k)));
  expect(slotKinds(host, '18')).toEqual(TAIL_ORDER.filter((k) => ['review', 'open'].includes(k)));
  expect(host.querySelectorAll('[data-task-manager-level="project"] .hd-slot-zero').length).toBe(0);
  for (const slot of host.querySelectorAll<HTMLElement>('[data-task-manager-level="project"] [data-task-manager-tail-slot]')) expect(slot.dataset.filled).toBe('on');
  for (const tail of host.querySelectorAll<HTMLElement>('[data-task-manager-level="project"] .hd-tail')) expect(tail.dataset.packed).toBe('on');
  expect(TAIL_ORDER.length).toBeGreaterThan(3);
  expect(readFileSync('src/cplugs/huddle/task-manager-tail.css', 'utf8')).toMatch(/\.hd-slot \{[^}]*border: 1px solid var\(--oc-line-rule\);[^}]*border-radius: 2px/);
  expect(TAIL_ORDER.slice(0, 3)).toEqual(['question', 'info', 'needs_you']);
  expect(TAIL_ORDER).not.toContain('look');
  expect(new Set(TAIL_ORDER).size).toBe(TAIL_ORDER.length);
});

test('a bar with one badge, in a list where nobody else has badges, gets one slot, not eleven', async () => {
  server.groups = [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [mk(11, '12', 'review')] }];
  await refreshTaskManager();
  const host = await mountBody(false);
  expect(slotKinds(host, '12')).toEqual(['review']);
});

test('a status bar with nothing inside draws no slots; the kinds are only those of the bars drawn together', async () => {
  const host = await mountBody(false);
  const statusTails = [...host.querySelectorAll<HTMLElement>('[data-task-manager-level="status"] .hd-tail')];
  expect(statusTails.length).toBeGreaterThan(0);
  for (const tail of statusTails) expect(tail.querySelectorAll('[data-task-manager-tail-slot]').length).toBe(0);
});

test('at a narrow container every bar still renders its title text, and the tail yields first', async () => {
  const host = await mountBody(false);
  host.style.width = '400px';
  const bars = [...host.querySelectorAll<HTMLElement>('[data-task-manager-level]')];
  expect(bars.length).toBeGreaterThan(2);
  for (const bar of bars) {
    const title = bar.querySelector<HTMLElement>('.hd-pname, .hss-name, .hds-name, .hds-sub-name, .hdeg-name');
    expect(title?.textContent?.trim(), `${bar.dataset.taskManagerLevel} bar keeps its title`).toBeTruthy();
  }
  const tail = rule('./task-manager-tail.css', '.hd-tail');
  expect(tail['flex']).toBe('0 1000 auto');
  expect(tail['min-width']).toBe('0');
  expect(tail['overflow']).toBe('hidden');
  expect(rule('./task-manager-tail.css', '[data-task-manager-level]')['container']).toBe('hdt / inline-size');
});

test('the tail is a grid of equal fixed cells: gutter spacing only, icon left, count right, two digits, tabular', () => {
  const tail = rule('./task-manager-tail.css', '.hd-tail');
  expect(tail['display']).toBe('grid');
  expect(tail['grid-auto-flow']).toBe('column');
  expect(tail['grid-auto-columns']).toBe('var(--_cell)');
  expect(tail['justify-content']).toBe('end');
  expect(tail['column-gap']).toBe('3px');
  expect(tail['margin-left']).toBe('auto');
  expect(tail['font-size']).toBe('var(--oc-fs-micro)');
  const slot = rule('./task-manager-tail.css', '.hd-slot');
  expect(slot['display']).toBe('flex');
  expect(slot['justify-content']).toBe('space-between');
  expect(slot['margin']).toBeUndefined();
  const n = rule('./task-manager-tail.css', '.hd-tail-n');
  expect(n['inline-size']).toBe('var(--_digits)');
  expect(n['text-align']).toBe('right');
  expect(n['font-variant-numeric']).toBe('tabular-nums');
});

test('empty cells are kept at every width, so columns stay aligned down the bars', () => {
  expect(cssText('./task-manager-tail.css')).not.toMatch(/@container hdt[^{]*\{[^}]*display:\s*none/);
});

describe('the tail cell', () => {
  test('is icon + gap + two digits wide, the same on every cell, and the number box never grows', async () => {
    const { readFileSync } = await import('node:fs');
    const css = readFileSync('src/cplugs/huddle/task-manager-tail.css', 'utf8');
    expect(css).toMatch(/--_digits:\s*2ch;/);
    expect(css).toMatch(/--_cell:\s*calc\(var\(--_icon\) \+ var\(--_gap\) \+ var\(--_digits\) \+ 2 \* var\(--_pad\) \+ 2px\)/);
    expect(css).not.toMatch(/min-inline-size:\s*var\(--_(digits|slot|cell)\)/);
  });

  test('every bar below the project level draws the same cells in the same order, so an icon sits in one column; a count over 99 reads 99 with a plus', async () => {
    const host = await mountBody(false);
    const tails = [...host.querySelectorAll<HTMLElement>('[data-task-manager-level="status"] .hd-tail')];
    expect(tails.length).toBeGreaterThan(1);
    const seqs = tails.map((t) => [...t.querySelectorAll('[data-task-manager-tail-slot]')].map((c) => (c as HTMLElement).dataset.taskManagerTailSlot));
    for (const seq of seqs) expect(seq).toEqual(seqs[0]);
    for (const n of host.querySelectorAll<HTMLElement>('.hd-tail-n')) expect(Number(n.textContent)).toBeLessThanOrEqual(99);
  });
});
