/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string, section: string) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section,
});

const server = vi.hoisted(() => ({ groups: [] as unknown[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 3, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '12', name: 'alpha', project_id: 12, items: 3, open: 3, review: 1, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import { COUNTS_HIDDEN_KEY, HIDDEN_SECTIONS_KEY, reloadCountsHidden, reloadHiddenSections, resetAccordion, setSectionHidden, hiddenSections } from './task-manager-status-folds.svelte';
import { AGGREGATE } from './huddle-model';
import { SECTION_ORDER } from './task-manager-status-sections';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function mountBody(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

async function remount(): Promise<HTMLElement> {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  reloadHiddenSections();
  return mountBody();
}

beforeEach(async () => {
  Element.prototype.scrollTo = vi.fn();
  server.groups = [
    { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [mk(1, '12', 'open'), mk(2, '12', 'open'), mk(3, '12', 'review')] },
    { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'done')] },
  ];
  localStorage.removeItem(HIDDEN_SECTIONS_KEY);
  hiddenSections.keys = [];
  localStorage.removeItem(COUNTS_HIDDEN_KEY);
  reloadCountsHidden();
  resetAccordion();
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  taskManagerPrefs.accordion = false;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const keyOf = (host: HTMLElement, section: string): HTMLElement => host.querySelector<HTMLElement>(`[data-task-manager-filter-key="${section}"]`)!;
const toggle = (host: HTMLElement): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-filter-toggle]')!;
const card = (host: HTMLElement): Element | null => host.querySelector('[data-task-manager-filter-card][data-open="on"]');
async function openCard(host: HTMLElement): Promise<void> {
  if (!card(host)) { toggle(host).click(); await settle(); }
}
const rows = (host: HTMLElement): number => host.querySelectorAll('[data-huddle-item]').length;

describe('the status filter', () => {
  test('every toggle is on by default and counts its items', async () => {
    const host = await mountBody();
    expect(card(host)).toBeNull();
    await openCard(host);
    const keys = [...host.querySelectorAll<HTMLElement>('[data-task-manager-filter-key]')];
    expect(keys.map((k) => k.dataset.taskManagerFilterKey)).toEqual([...SECTION_ORDER]);
    expect(keys.every((k) => k.getAttribute('aria-pressed') === 'true')).toBe(true);
    expect(keyOf(host, 'open').textContent?.trim()).toBe('');
    expect(keyOf(host, 'open').getAttribute('title')).toContain('2');
    expect(rows(host)).toBe(3);
  });

  test('clicking a toggle hides its rows, again shows them, and a remount keeps it hidden', async () => {
    let host = await mountBody();
    await openCard(host);
    keyOf(host, 'open').click();
    await settle();
    expect(keyOf(host, 'open').getAttribute('aria-pressed')).toBe('false');
    expect(rows(host)).toBe(1);
    host = await remount();
    expect(card(host)).toBeNull();
    await openCard(host);
    expect(keyOf(host, 'open').getAttribute('aria-pressed')).toBe('false');
    expect(rows(host)).toBe(1);
    keyOf(host, 'open').click();
    await settle();
    expect(rows(host)).toBe(3);
  });

  test('hiding the only status in a project removes its project row, showing it brings the row back', async () => {
    const host = await mountBody();
    await openCard(host);
    const head = (list: string): Element | null => host.querySelector(`[data-task-manager-project-scroll="${list}"]`);
    expect(head('18')).not.toBeNull();
    keyOf(host, 'done').click();
    await settle();
    expect(head('18')).toBeNull();
    expect(head('12')).not.toBeNull();
    keyOf(host, 'done').click();
    await settle();
    expect(head('18')).not.toBeNull();
  });

  test('a hidden section with something for the owner wears the needs marker; one with nothing does not', async () => {
    const host = await mountBody();
    await openCard(host);
    keyOf(host, 'review').click();
    keyOf(host, 'open').click();
    await settle();
    expect(keyOf(host, 'review').getAttribute('data-task-manager-filter-needs')).toBe('on');
    expect(keyOf(host, 'open').getAttribute('data-task-manager-filter-needs')).toBeNull();
    expect(host.querySelector('[data-task-manager-filter-toggle] .hdf-needs')).not.toBeNull();
  });

  test('the funnel changes state when anything is hidden, and the card opens, closes on Escape and on an outside press', async () => {
    const host = await mountBody();
    expect(toggle(host).getAttribute('data-task-manager-filter-state')).toBe('all');
    await openCard(host);
    expect(card(host)).not.toBeNull();
    expect(card(host)!.closest('.hd-bar')).not.toBeNull();
    expect(card(host)!.querySelectorAll(':scope > [data-task-manager-filter-key]').length).toBe(SECTION_ORDER.length);
    keyOf(host, 'done').click();
    await settle();
    expect(toggle(host).getAttribute('data-task-manager-filter-state')).toBe('filtered');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();
    expect(card(host)).toBeNull();
    await openCard(host);
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    await settle();
    expect(card(host)).toBeNull();
    await openCard(host);
    keyOf(host, 'done').click();
    await settle();
    expect(toggle(host).getAttribute('data-task-manager-filter-state')).toBe('all');
  });

  test('restoring writes nothing and an unknown stored status is ignored', () => {
    localStorage.setItem(HIDDEN_SECTIONS_KEY, JSON.stringify(['done', 'gone_status']));
    const write = vi.spyOn(Storage.prototype, 'setItem');
    reloadHiddenSections();
    expect(hiddenSections.keys).toEqual(['done']);
    expect(write).not.toHaveBeenCalled();
    write.mockRestore();
    setSectionHidden('done', false);
    expect(hiddenSections.keys).toEqual([]);
  });

  test('the eye hides the count badges in the bars, keeps every row, and a remount keeps it off (#1840)', async () => {
    let host = await mountBody();
    const eye = (): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-counts-toggle]')!;
    expect(eye().getAttribute('data-task-manager-counts-state')).toBe('shown');
    expect(host.querySelectorAll('[data-task-manager-tail-slot][data-filled="on"]').length).toBeGreaterThan(0);
    const before = rows(host);
    eye().click();
    await settle();
    expect(eye().getAttribute('data-task-manager-counts-state')).toBe('hidden');
    expect(host.querySelectorAll('[data-task-manager-tail-slot]').length).toBe(0);
    expect(rows(host)).toBe(before);
    host = await remount();
    expect(eye().getAttribute('data-task-manager-counts-state')).toBe('hidden');
    reloadCountsHidden();
    eye().click();
    await settle();
    expect(host.querySelectorAll('[data-task-manager-tail-slot][data-filled="on"]').length).toBeGreaterThan(0);
  });
});
