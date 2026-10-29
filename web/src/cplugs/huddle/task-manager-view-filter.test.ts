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
import { FOLDS_KEY, isFolded, projectFoldKey, statusFolds } from './task-manager-status-folds.svelte';
import { AGGREGATE, type HuddleItem } from './huddle-model';
import {
  clearViewFilter, dropUnusedMarkers, filterView, matchesView, toggleViewMarker, toggleViewStatus, viewFilter, viewFilterActive, setViewQuery,
} from './task-manager-view-filter.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

const item = (extra: Record<string, unknown>): HuddleItem => mk(1, '12', 'open', extra) as unknown as HuddleItem;

describe('matchesView (pure)', () => {
  const off = { query: '', markers: [], status: null } as const;

  test('nothing filtered shows every item and is not active', () => {
    expect(matchesView(item({}), { ...off, markers: [] })).toBe(true);
    expect(viewFilterActive({ ...off, markers: [] })).toBe(false);
  });

  test('markers: any picked shape shows; an unmarked item never does', () => {
    const f = { ...off, markers: ['star', 'cross'] as ('star' | 'cross')[] };
    expect(matchesView(item({ marker: 'star' }), f)).toBe(true);
    expect(matchesView(item({ marker: 'cross' }), f)).toBe(true);
    expect(matchesView(item({ marker: 'circle' }), f)).toBe(false);
    expect(matchesView(item({}), f)).toBe(false);
  });

  test('status: the item\'s own status section, ignoring needs you', () => {
    const f = { ...off, markers: [], status: 'review' as const };
    expect(matchesView(mk(2, '12', 'review', { needs_you: true }) as unknown as HuddleItem, f)).toBe(true);
    expect(matchesView(item({}), f)).toBe(false);
  });

  test('search: a fuzzy match on the title or the text; the parts combine with AND', () => {
    const f = { query: 'shpit', markers: ['star'] as 'star'[], status: null };
    expect(matchesView(item({ text: 'ship it today', marker: 'star' }), f)).toBe(true);
    expect(matchesView(item({ text: 'ship it today' }), f)).toBe(false);
    expect(matchesView(item({ text: 'unrelated', title: 'ship it', marker: 'star' }), f)).toBe(true);
    expect(matchesView(item({ text: 'unrelated', marker: 'star' }), f)).toBe(false);
  });

  test('filterView returns the same array when nothing is filtered', () => {
    const items = [item({}), item({ marker: 'star' })];
    expect(filterView(items, off)).toBe(items);
    expect(filterView(items, { ...off, markers: ['star'] })).toHaveLength(1);
  });
});

describe('the store', () => {
  afterEach(() => clearViewFilter());

  test('toggling shapes and statuses, and a second status press clears', () => {
    toggleViewMarker('star', true);
    toggleViewMarker('star', true);
    expect(viewFilter.markers).toEqual(['star']);
    toggleViewMarker('star', false);
    expect(viewFilter.markers).toEqual([]);
    toggleViewStatus('review');
    expect(viewFilter.status).toBe('review');
    toggleViewStatus('review');
    expect(viewFilter.status).toBeNull();
  });

  test('a stale shape drops out so a filter never hides everything with no key to undo it', () => {
    toggleViewMarker('star', true);
    toggleViewMarker('cross', true);
    dropUnusedMarkers(['cross']);
    expect(viewFilter.markers).toEqual(['cross']);
  });

  test('a live filter opens every fold without touching the stored choice', () => {
    statusFolds.choices = { [projectFoldKey('12')]: true };
    expect(isFolded(projectFoldKey('12'))).toBe(true);
    setViewQuery('x');
    expect(isFolded(projectFoldKey('12'))).toBe(false);
    clearViewFilter();
    expect(isFolded(projectFoldKey('12'))).toBe(true);
    statusFolds.choices = {};
  });
});

describe('the search in the list bar', () => {
  let app: ReturnType<typeof mount> | null = null;

  async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
      await Promise.resolve();
      await tick();
    }
    flushSync();
  }

  beforeEach(async () => {
    server.prefs = { revision: 3, settings: { hideCompleted: false } };
    server.groups = [
      { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
        mk(11, '12', 'open', { text: 'rebuild the review board' }), mk(12, '12', 'working', { text: 'fix the marker filter' }), mk(13, '12', 'open', { text: 'write docs' }),
      ] },
      { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'open', { text: 'review the board again' })] },
    ];
    statusFolds.choices = {};
    clearViewFilter();
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
    clearViewFilter();
    document.body.innerHTML = '';
  });

  const rows = (host: HTMLElement): number[] => [...host.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((el) => Number(el.dataset.huddleItem)).sort((a, b) => a - b);

  async function mountBody(): Promise<HTMLElement> {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    return host;
  }

  async function type(host: HTMLElement, text: string): Promise<void> {
    if (!host.querySelector('[data-task-manager-search]')) {
      host.querySelector<HTMLElement>('[data-task-manager-search-key]')!.click();
      await settle();
    }
    const field = host.querySelector<HTMLInputElement>('[data-task-manager-search]')!;
    field.value = text;
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
  }

  test('typing filters by a fuzzy match across every project and opens folded ones; the project with no match is not drawn', async () => {
    statusFolds.choices = { [projectFoldKey('12')]: true, [projectFoldKey('18')]: true };
    const host = await mountBody();
    expect(rows(host)).toEqual([]);
    await type(host, 'rvw brd');
    expect(rows(host)).toEqual([11, 21]);
    await type(host, 'marker');
    expect(rows(host)).toEqual([12]);
    expect(host.querySelector('[data-task-manager-heading="18"]')).toBeNull();
  });

  test('nothing matching says so; Escape empties the search and closes it, and the folds come back', async () => {
    statusFolds.choices = { [projectFoldKey('12')]: true };
    const host = await mountBody();
    await type(host, 'zzzzzz');
    expect(rows(host)).toEqual([]);
    expect(host.querySelector('[data-task-manager-empty]')!.textContent).toBe('nothing matches');
    host.querySelector<HTMLElement>('[data-task-manager-search]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(host.querySelector('[data-task-manager-search]')).toBeNull();
    expect(viewFilter.query).toBe('');
    expect(rows(host)).toEqual([21]);
    expect(statusFolds.choices[projectFoldKey('12')]).toBe(true);
  });

  test('the clear key drops the whole filter at once and appears only while a filter is on', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-filter-clear]')).toBeNull();
    await type(host, 'docs');
    expect(rows(host)).toEqual([13]);
    host.querySelector<HTMLElement>('[data-task-manager-filter-clear]')!.click();
    await settle();
    expect(rows(host)).toEqual([11, 12, 13, 21]);
    expect(host.querySelector('[data-task-manager-filter-clear]')).toBeNull();
  });
});
