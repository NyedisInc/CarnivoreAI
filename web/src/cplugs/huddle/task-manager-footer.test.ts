/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  calls: [] as { path: string; method: string }[],
  items: null as unknown[] | null,
  groups: [] as unknown[],
}));

const mk = (id: number, state = 'open', list = 'all') => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [],
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method });
      if (path === '/cplugs/huddle' && method === 'PUT') {
        const body = JSON.parse(String(init.body));
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 4, open: 2, review: 0, questions: 0, claude_seq: 0 }] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 7, cursor: 7, items: server.items ?? [mk(1), mk(2, 'done'), { ...mk(3, 'done'), note: 'read the note' }, mk(4)] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      return {};
    },
  };
});

import { FOOTER_ICON_PX } from './task-manager-footer';
import { huddle, refreshTaskManager } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';
import { refreshPrefs } from './task-manager-prefs.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout: boolean, view: 'status' | 'area' = 'status'): Promise<HTMLElement> {
  server.prefs = { revision: 3, settings: { view } };
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

function keyOrder(host: HTMLElement): string[] {
  const row = host.querySelector<HTMLElement>('[data-task-manager-controls]')!;
  return [...row.querySelectorAll<HTMLElement>('button')].map((b) => Object.keys(b.dataset).find((k) => k.startsWith('taskManager'))!);
}

beforeEach(() => {
  server.calls = [];
  server.items = null;
  server.groups = [];
  huddle.selected = 'all';
  huddle.groups = null;
  huddle.openId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s key row', (_name, popout) => {
  test('icons only: every key is named by a tooltip and an aria-label, and no key carries words', async () => {
    const host = await mountBody(popout, 'area');
    const keys = [...host.querySelectorAll<HTMLElement>('[data-task-manager-controls] button')];
    expect(keys.length).toBeGreaterThanOrEqual(5);
    for (const key of keys) {
      expect(key.getAttribute('aria-label')).toBeTruthy();
      expect(key.getAttribute('title')).toBeTruthy();
    }
    expect(host.querySelector('[data-huddle-key-label], .hd-key-label')).toBeNull();
    for (const key of keys.filter((k) => !k.hasAttribute('data-task-manager-remove-completed') && !k.hasAttribute('data-task-manager-send'))) {
      expect(key.querySelector('svg')).not.toBeNull();
      expect(key.textContent!.trim()).toBe('');
    }
  });

  test('remove completed is a trash icon beside the count, far left; its confirm says it deletes, and only the confirm acts', async () => {
    const host = await mountBody(popout, 'area');
    expect(keyOrder(host)[0]).toBe('taskManagerRemoveCompleted');
    const count = host.querySelector<HTMLElement>('[data-task-manager-remove-completed]')!;
    expect(count.textContent!.trim()).toBe('2');
    expect(count.querySelector('svg')).not.toBeNull();
    expect(count.getAttribute('aria-label')).toBe('remove completed (2)');
    count.click();
    flushSync();
    expect(host.querySelector('[data-task-manager-remove-ask]')!.textContent).toBe('delete the 2 checked items in this list? they are gone for good, not hidden.');
    expect(server.calls.some((c) => c.path.endsWith('/remove-completed'))).toBe(false);
    host.querySelector<HTMLElement>('[data-task-manager-remove-cancel]')!.click();
    flushSync();
    expect(host.querySelector('[data-task-manager-remove-ask]')).toBeNull();
    expect(server.calls.some((c) => c.path.endsWith('/remove-completed'))).toBe(false);
    host.querySelector<HTMLElement>('[data-task-manager-remove-completed]')!.click();
    flushSync();
    host.querySelector<HTMLElement>('[data-task-manager-remove-confirm]')!.click();
    await settle();
    expect(server.calls.filter((c) => c.path.endsWith('/remove-completed'))).toEqual([{ path: '/cplugs/huddle/lists/all/remove-completed', method: 'POST' }]);
  });

  test('the group keys show only in the by group view, right after the count', async () => {
    const byStatus = await mountBody(popout, 'status');
    expect(byStatus.querySelector('[data-task-manager-new-group]')).toBeNull();
    expect(byStatus.querySelector('[data-task-manager-show-empty-groups]')).toBeNull();
    expect(keyOrder(byStatus)).toEqual(['taskManagerRemoveCompleted', 'taskManagerHideCompleted', 'taskManagerSend']);
    unmount(app!);
    app = null;
    document.body.innerHTML = '';
    const byGroup = await mountBody(popout, 'area');
    expect(keyOrder(byGroup)).toEqual(['taskManagerRemoveCompleted', 'taskManagerNewGroup', 'taskManagerShowEmptyGroups', 'taskManagerHideCompleted', 'taskManagerSend']);
    expect(byGroup.querySelector('.hd-foot-right [data-task-manager-show-empty-groups]')).toBeNull();
  });

  test('hide completed is one icon that shows its state', async () => {
    const host = await mountBody(popout);
    const key = host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!;
    expect(key.getAttribute('aria-pressed')).toBe('false');
    expect(key.querySelectorAll('svg')).toHaveLength(1);
    expect(key.querySelector('svg')!.getAttribute('data-icon')).toBe('eye-check');
    key.click();
    await settle();
    expect(key.getAttribute('aria-pressed')).toBe('true');
    expect(key.querySelector('svg')!.getAttribute('data-icon')).toBe('eye-check-off');
    expect(key.getAttribute('title')).toBe('checked items are hidden; press to show them again');
  });

  test('the add box is its own section under the key row, and the icons are a whole-pixel 16', async () => {
    const host = await mountBody(popout, 'area');
    const row = host.querySelector<HTMLElement>('[data-task-manager-controls]')!;
    expect(row.nextElementSibling?.classList.contains('hd-add')).toBe(true);
    expect(row.contains(host.querySelector('[data-task-manager-add]'))).toBe(false);
    const sizes = [...row.querySelectorAll('svg')].map((svg) => svg.getAttribute('width'));
    expect(sizes.length).toBeGreaterThanOrEqual(4);
    expect(new Set(sizes)).toEqual(new Set([String(FOOTER_ICON_PX)]));
  });
});

test('no needs a decision strip at the top of the list', async () => {
  const host = await mountBody(false);
  expect(host.querySelector('[data-huddle-item="1"]')).not.toBeNull();
  expect(host.querySelector('[data-huddle-flag-legend], .hd-flags')).toBeNull();
});

test('one checked item reads in the singular', async () => {
  server.items = [mk(1), mk(2, 'done')];
  const host = await mountBody(false);
  host.querySelector<HTMLElement>('[data-task-manager-remove-completed]')!.click();
  flushSync();
  expect(host.querySelector('[data-task-manager-remove-ask]')!.textContent).toBe('delete the checked item in this list? it is gone for good, not hidden.');
});

test('all projects: the count and the delete cover the same lists, and an agent list is in neither', async () => {
  server.groups = [
    { list: '12', name: 'alpha', project_id: 12, revision: 4, groups: [], items: [mk(11, 'done', '12'), mk(12, 'done', '12'), mk(13, 'open', '12')] },
    { list: 'agent:5', name: null, project_id: null, revision: 2, groups: [],
      items: [mk(51, 'done', 'agent:5'), mk(52, 'done', 'agent:5'), mk(53, 'done', 'agent:5')] },
  ];
  huddle.selected = AGGREGATE;
  const host = await mountBody(false);
  const count = host.querySelector<HTMLElement>('[data-task-manager-remove-completed]')!;
  expect(count.textContent!.trim()).toBe('2');
  count.click();
  flushSync();
  expect(host.querySelector('[data-task-manager-remove-ask]')!.textContent)
    .toBe('delete the 2 checked items across all projects? they are gone for good, not hidden.');
  host.querySelector<HTMLElement>('[data-task-manager-remove-confirm]')!.click();
  await settle();
  expect(server.calls.filter((c) => c.path.endsWith('/remove-completed'))).toEqual([{ path: '/cplugs/huddle/lists/12/remove-completed', method: 'POST' }]);
});
