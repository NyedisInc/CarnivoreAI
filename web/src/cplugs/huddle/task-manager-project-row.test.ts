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
import { FOLDS_KEY, projectFoldKey, setSectionFolded, statusFolds } from './task-manager-status-folds.svelte';
import { readFileSync } from 'node:fs';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { AGGREGATE } from './huddle-model';
import { clearViewFilter } from './task-manager-view-filter.svelte';
import HuddleBody from './HuddleBody.svelte';
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

const GROUPS = () => [
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'question'), mk(12, '12', 'question'),
    mk(13, '12', 'review'), mk(14, '12', 'review'),
    mk(15, '12', 'scheduled', { start_trigger: { kind: 'at', fire_at: 2_000_000_000, fired_at: null, last_error: null } }),
  ] },
  { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review')] },
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  clearViewFilter();
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  window.location.hash = '';
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  clearViewFilter();
  document.body.innerHTML = '';
});

const alpha = (host: HTMLElement): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-level="project"]')!;
const slot = (host: HTMLElement, kind: string): HTMLElement | null => host.querySelector<HTMLElement>(`[data-task-manager-tail="12"] [data-task-manager-tail-slot="${kind}"]`);

/** Whether a comes before b in document order. */
const before = (a: Element, b: Element): boolean => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('the project row', () => {
  test('reads chevron, nudge, count, title, then the badges', async () => {
    const host = await mountBody(false);
    const head = alpha(host);
    const parts = ['[data-task-manager-project-fold]', '[data-task-manager-project-nudge]', '[data-task-manager-project-count]', '[data-task-manager-heading]', '[data-task-manager-tail]']
      .map((selector) => head.querySelector(selector)!);
    for (let i = 0; i < parts.length - 1; i += 1) expect(before(parts[i]!, parts[i + 1]!), `part ${i}`).toBe(true);
  });

  test('a status with nothing in it is not drawn, and the filled badges are the only cells', async () => {
    const host = await mountBody(false);
    const kinds = [...host.querySelectorAll<HTMLElement>('[data-task-manager-tail="12"] [data-task-manager-tail-slot]')].map((s) => s.dataset.taskManagerTailSlot);
    expect(kinds).toEqual(['question', 'review', 'scheduled']);
    expect(slot(host, 'working')).toBeNull();
    expect(host.querySelector('[data-task-manager-level="project"] .hd-slot-zero')).toBeNull();
  });

  test('the count is a bare number in a rounded rect two digits wide, centered, no icon', async () => {
    const host = await mountBody(false);
    const chip = alpha(host).querySelector<HTMLElement>('[data-task-manager-project-count]')!;
    expect(chip.textContent?.trim()).toBe('5');
    expect(chip.querySelector('svg, [data-icon]')).toBeNull();
    const css = readFileSync('src/cplugs/huddle/TaskManagerProjectHead.svelte', 'utf8');
    const rule = css.slice(css.indexOf('.hd-pcount {'), css.indexOf('}', css.indexOf('.hd-pcount {')));
    expect(rule).toMatch(/min-inline-size: calc\(2ch/);
    expect(rule).toMatch(/border-radius: 2px/);
    expect(rule).toMatch(/text-align: center/);
    expect(rule).toMatch(/tabular-nums/);
  });
});

const shown = (host: HTMLElement): number[] => [...host.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((el) => Number(el.dataset.huddleItem)).sort((x, y) => x - y);

describe('a status badge filters the tree and lights up (Part 4, #1709, ruling 3)', () => {
  test('pressing the review badge shows only reviews in every project with all open; the badge is lit; a second press clears', async () => {
    const host = await mountBody(false);
    expect(shown(host)).toEqual([11, 12, 13, 14, 15, 21]);
    expect(document.querySelector('[data-task-manager-status-modal]')).toBeNull();
    slot(host, 'review')!.click();
    await settle();
    expect(shown(host)).toEqual([13, 14, 21]);
    expect(slot(host, 'review')!.dataset.active).toBe('on');
    expect(slot(host, 'review')!.getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('[data-task-manager-status-modal]')).toBeNull();
    slot(host, 'review')!.click();
    await settle();
    expect(shown(host)).toEqual([11, 12, 13, 14, 15, 21]);
    expect(slot(host, 'review')!.dataset.active).toBeUndefined();
  });

  test('a folded project opens while its badge filters, and keeps its stored fold after', async () => {
    setSectionFolded(projectFoldKey('12'), true);
    const host = await mountBody(false);
    expect(shown(host)).toEqual([21]);
    slot(host, 'question')!.click();
    await settle();
    expect(shown(host)).toEqual([11, 12]);
    host.querySelector<HTMLElement>('[data-task-manager-filter-clear]')!.click();
    await settle();
    expect(shown(host)).toEqual([21]);
    expect(statusFolds.choices[projectFoldKey('12')]).toBe(true);
  });

  test('for every status, the filtered rows equal the number on its badge, all of that status', async () => {
    const MIX: [string, number][] = [['question', 3], ['review', 2], ['waiting', 1], ['working', 4], ['scheduled', 2], ['open', 5]];
    let id = 100;
    server.groups = [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: MIX.flatMap(([status, n]) => Array.from({ length: n }, () => {
      id += 1;
      return mk(id, '12', status, status === 'scheduled' ? { start_trigger: { kind: 'at', fire_at: 2_000_000_000, fired_at: null, last_error: null } } : {});
    })) }];
    await refreshTaskManager();
    const host = await mountBody(false);
    for (const [status, n] of MIX) {
      const badge = slot(host, status)!;
      expect(Number(badge.querySelector('.hd-tail-n')!.textContent), `${status} badge`).toBe(n);
      badge.click();
      await settle();
      const rows = [...host.querySelectorAll<HTMLElement>('[data-huddle-item]')];
      expect(rows.length, `${status} rows`).toBe(n);
      for (const row of rows) expect(row.dataset.status).toBe(status);
      slot(host, status)!.click();
      await settle();
    }
  });
});

describe('the info badge opens a read-and-dismiss modal; the other badges never do', () => {
  const post = (id: number, item: number, kind: string, text: string) => ({ id, item_id: item, author: 'claude', kind, text, answered: false, created_at: 1_900_000_000 + id, seq: id, unread: true });
  const INFOS = () => [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(31, '12', 'open', { thread: [post(1, 31, 'info', 'first info'), post(2, 31, 'info', 'second info'), post(3, 31, 'attention', 'look at this')], info_unread: 2, attention_unread: 1 }),
    mk(32, '12', 'open', { thread: [post(4, 32, 'info', 'third info')], info_unread: 1 }),
    mk(33, '12', 'todo'), mk(34, '12', 'todo'),
  ] }];

  test('a folded bar draws an info key and no look badge; the modal lists one row per unread info, and Escape or close removes it', async () => {
    server.groups = INFOS();
    await refreshTaskManager();
    setSectionFolded(projectFoldKey('12'), true);
    const host = await mountBody(false);
    expect(slot(host, 'look')).toBeNull();
    const info = slot(host, 'info')!;
    expect(info.tagName).toBe('BUTTON');
    expect(Number(info.querySelector('.hd-tail-n')!.textContent)).toBe(3);
    info.click();
    await settle();
    const modal = document.querySelector<HTMLElement>('[data-task-manager-status-modal="info"]')!;
    expect(modal.querySelectorAll('[data-task-manager-list-row]').length).toBe(3);
    expect([...modal.querySelectorAll('.hl-title')].map((el) => el.textContent).sort()).toEqual(['first info', 'second info', 'third info']);
    document.querySelector<HTMLElement>('[data-task-manager-status-modal-close]')!.click();
    await settle();
    expect(document.querySelector('.modal-overlay')).toBeNull();
    info.click();
    await settle();
    document.querySelector<HTMLElement>('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(document.querySelector('[data-task-manager-status-modal]')).toBeNull();
  });

  test('the back burner badge filters like the other statuses and opens no modal', async () => {
    server.groups = INFOS();
    await refreshTaskManager();
    const host = await mountBody(false);
    slot(host, 'todo')!.click();
    await settle();
    expect(document.querySelector('[data-task-manager-status-modal]')).toBeNull();
    expect(shown(host)).toEqual([33, 34]);
  });

  test('the action of every badge kind: info opens the modal, a status filters, needs you does nothing', async () => {
    const { badgeAction, isClickable } = await import('./task-manager-status-modal');
    expect(badgeAction('info')).toBe('modal');
    for (const kind of ['question', 'review', 'waiting', 'working', 'scheduled', 'open', 'todo', 'done'] as const) expect(badgeAction(kind), kind).toBe('filter');
    expect(badgeAction('needs_you')).toBeNull();
    expect(isClickable('needs_you')).toBe(false);
    expect(isClickable('info') && isClickable('review')).toBe(true);
  });

  test('a badge that is not a key is not a button and its cell shows no pointer', async () => {
    const css = readFileSync('src/cplugs/huddle/task-manager-tail.css', 'utf8');
    expect(css).toMatch(/\.hd-slot:not\(\.hd-slot-key\) \{[^}]*cursor: default/);
    server.groups = [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [mk(11, '12', 'open', { needs_you: true, needs_action: 'read' })] }];
    await refreshTaskManager();
    const host = await mountBody(false);
    const needs = slot(host, 'needs_you');
    if (needs) expect(needs.tagName).not.toBe('BUTTON');
  });
});

describe('the title folds, the rest of the bar scrolls', () => {
  test('a click on the title folds the project and does not scroll it', async () => {
    const host = await mountBody(false);
    expect(shown(host)).toContain(11);
    host.querySelector<HTMLElement>('[data-task-manager-project-title="12"]')!.click();
    await settle();
    expect(statusFolds.choices[projectFoldKey('12')]).toBe(true);
    expect(shown(host)).not.toContain(11);
    host.querySelector<HTMLElement>('[data-task-manager-project-title="12"]')!.click();
    await settle();
    expect(shown(host)).toContain(11);
  });
});

describe('the gap between the chevron, the bell and the count', () => {
  test('is one small token, 2 to 4px, used by all three', () => {
    const css = readFileSync('src/cplugs/huddle/TaskManagerProjectHead.svelte', 'utf8');
    const px = Number(/--_row-gap:\s*(\d+)px/.exec(css)?.[1]);
    expect(px).toBeGreaterThanOrEqual(2);
    expect(px).toBeLessThanOrEqual(4);
    expect(css).toMatch(/\.hd-pchev \{[^}]*padding: 0 var\(--_row-gap\) 0 10px/);
    expect(css).toMatch(/\.hd-pnudge \{[^}]*margin-right: var\(--_row-gap\)/);
  });
});
