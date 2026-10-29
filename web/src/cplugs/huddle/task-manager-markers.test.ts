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
import { statusFolds, FOLDS_KEY } from './task-manager-status-folds.svelte';
import { STATUS_COLOR } from './huddle-status';
import { MARKERS, MARKER_PATH, MARKER_TOKEN, markerOf, markersInUse } from './task-manager-markers';
import { clearViewFilter } from './task-manager-view-filter.svelte';
import { AGGREGATE } from './huddle-model';
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

const GROUPS = (marked: boolean) => [
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'open', marked ? { marker: 'star' } : {}),
    mk(12, '12', 'working', marked ? { marker: 'star' } : {}),
    mk(13, '12', 'review', marked ? { marker: 'cross' } : {}),
    mk(14, '12', 'open', marked ? { marker: 'hexagon' } : {}),
    mk(15, '12', 'open'),
  ] },
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS(true);
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

const shown = (host: HTMLElement): number[] => [...host.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((el) => Number(el.dataset.huddleItem)).sort((a, b) => a - b);

test('eight distinct shapes, each with its own path and its own series token, none a status color', () => {
  expect(MARKERS).toHaveLength(8);
  expect(new Set(MARKERS.map((id) => MARKER_PATH[id])).size).toBe(8);
  expect(new Set(MARKERS.map((id) => MARKER_TOKEN[id])).size).toBe(8);
  const statusTokens = new Set(Object.values(STATUS_COLOR));
  for (const id of MARKERS) expect(statusTokens.has(MARKER_TOKEN[id])).toBe(false);
});

test('an unknown or absent id is no marker; the set lists only the shapes in use, in the fixed order', () => {
  expect(markerOf({ marker: 'orange' })).toBeNull();
  expect(markerOf({ marker: null })).toBeNull();
  expect(markerOf({})).toBeNull();
  expect(markerOf({ marker: 'star' })).toBe('star');
  expect(markersInUse([{ marker: 'cross' }, { marker: 'diamond' }, { marker: 'cross' }, {}])).toEqual([{ id: 'diamond', count: 1 }, { id: 'cross', count: 2 }]);
  expect(markersInUse([{}, { marker: 'nope' }])).toEqual([]);
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('a marked row wears its shape in the margin, outside the grid, and its stripe stays the status color', async () => {
    const host = await mountBody(popout);
    const row = host.querySelector<HTMLElement>('[data-huddle-item="12"]')!;
    expect(row.dataset.taskManagerMarker).toBe('star');
    const mark = row.querySelector<HTMLElement>('[data-task-manager-row-marker="12"] [data-task-manager-marker="star"]');
    expect(mark).not.toBeNull();
    expect(mark!.querySelector('path')!.getAttribute('d')).toBe(MARKER_PATH.star);
    expect(row.getAttribute('style')).not.toContain(MARKER_TOKEN.star);
    expect(row.dataset.status).toBe('working');
    expect(row.querySelector('[data-task-manager-status-icon="working"]')).not.toBeNull();
    const plain = host.querySelector<HTMLElement>('[data-huddle-item="15"]')!;
    expect(plain.dataset.taskManagerMarker).toBeUndefined();
    expect(plain.querySelector('[data-task-manager-row-marker]')).toBeNull();
  });

  test('the header filter set shows only the shapes in use', async () => {
    const host = await mountBody(popout);
    const keys = [...host.querySelectorAll<HTMLElement>('[data-task-manager-marker-key]')].map((el) => el.dataset.taskManagerMarkerKey);
    expect(keys).toEqual(['hexagon', 'star', 'cross']);
  });

  test('nothing marked: no filter set and no marked row', async () => {
    server.groups = GROUPS(false);
    await refreshTaskManager();
    const host = await mountBody(popout);
    expect(host.querySelector('[data-task-manager-marker-filter]')).toBeNull();
    expect(host.querySelector('[data-task-manager-marker]')).toBeNull();
  });

  test('pressing a shape shows only those tasks, with the project open; pressing again restores the list', async () => {
    const host = await mountBody(popout);
    expect(shown(host)).toEqual([11, 12, 13, 14, 15]);
    host.querySelector<HTMLElement>('[data-task-manager-marker-key="star"]')!.click();
    await settle();
    expect(shown(host)).toEqual([11, 12]);
    expect(host.querySelector('[data-task-manager-marker-key="star"]')!.getAttribute('aria-pressed')).toBe('true');
    host.querySelector<HTMLElement>('[data-task-manager-marker-key="cross"]')!.click();
    await settle();
    expect(shown(host)).toEqual([11, 12, 13]);
    host.querySelector<HTMLElement>('[data-task-manager-marker-key="star"]')!.click();
    host.querySelector<HTMLElement>('[data-task-manager-marker-key="cross"]')!.click();
    await settle();
    expect(shown(host)).toEqual([11, 12, 13, 14, 15]);
  });

  test('a folded project opens while a shape is picked and folds back when the filter clears', async () => {
    statusFolds.choices = { 'project/12': true };
    const host = await mountBody(popout);
    expect(shown(host)).toEqual([]);
    host.querySelector<HTMLElement>('[data-task-manager-marker-key="cross"]')!.click();
    await settle();
    expect(shown(host)).toEqual([13]);
    host.querySelector<HTMLElement>('[data-task-manager-filter-clear]')!.click();
    await settle();
    expect(shown(host)).toEqual([]);
    expect(statusFolds.choices['project/12']).toBe(true);
  });
});
