/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { menuNode, openRowMenu } from './row-menu-driver.test.helper';

const mk = (id: number, section: string, position: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position, created_by: 'joe', state: section === 'todo' ? 'todo' : 'open', kind: '',
  number: null, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  view: 'status', items: [] as unknown[], patches: [] as { path: string; body: Record<string, unknown> }[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH') server.patches.push({ path, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 2 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'widgets', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { DEFAULT_FOLDED, SECTION_ICON, SECTION_ORDER, sectionOf, statusSections } from './task-manager-status-sections';
import { FOLDS_KEY, isFolded, sectionFoldKey, setSectionFolded, statusFolds } from './task-manager-status-folds.svelte';
import { STATUS_ICON, statusOf } from './huddle-status';
import type { HuddleItem } from './huddle-model';
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

const LIST = () => [
  mk(1, 'open', 0), mk(2, 'todo', 1), mk(3, 'todo', 2, { group: 7, note_waiting: true }),
  mk(4, 'done', 3, { state: 'done', status: 'done' }),
];

beforeEach(() => {
  statusFolds.choices = {};
  server.patches = [];
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = LIST();
  try { globalThis.localStorage?.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable in the test env */ }
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(view: string, popout: boolean): Promise<HTMLElement> {
  server.view = view;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

describe('the model', () => {
  test('back burner sits just above done, has its own icon, and is folded by default', () => {
    expect(SECTION_ORDER.slice(-2)).toEqual(['todo', 'done']);
    expect(DEFAULT_FOLDED).toContain('todo');
    expect(STATUS_ICON.todo).toBe('status-back-burner');
    expect(SECTION_ICON.todo).toBe('status-back-burner');
    const item = mk(2, 'todo', 1) as unknown as HuddleItem;
    expect(statusOf(item)).toBe('todo');
    expect(sectionOf(item)).toBe('todo');
    expect(statusSections(LIST() as unknown as HuddleItem[]).map((s) => s.key)).toEqual(['open', 'todo', 'done']);
  });

  test('the fold default holds per list and an explicit unfold persists', () => {
    expect(isFolded(sectionFoldKey('all', 'todo'))).toBe(true);
    expect(isFolded(sectionFoldKey('all', 'open'))).toBe(false);
    setSectionFolded(sectionFoldKey('all', 'todo'), false);
    expect(isFolded(sectionFoldKey('all', 'todo'))).toBe(false);
    expect(globalThis.localStorage?.getItem(FOLDS_KEY) ?? '').toContain('all/todo');
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('status view: a back burner section above done, folded (header only), unfolds on press', async () => {
    const host = await mountBody('status', popout);
    const heads = [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-head]')].map((h) => h.dataset.taskManagerStatusHead);
    expect(heads).toEqual(['open', 'todo', 'done']);
    const head = host.querySelector<HTMLElement>('[data-task-manager-status-head="todo"]')!;
    expect(head.dataset.folded).toBe('on');
    expect(host.querySelector('[data-task-manager-status-section="todo"] [data-huddle-item]')).toBeNull();
    expect(head.querySelector('[data-task-manager-section-icon]')).not.toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-status-fold="todo"]')!.click();
    await settle();
    const rows = [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-section="todo"] [data-huddle-item]')];
    expect(rows.map((r) => r.dataset.huddleItem).sort()).toEqual(['2', '3']);
    expect(rows[0]!.querySelector('[data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('todo');
    expect(host.querySelector('[data-huddle-note-waiting]')).toBeNull();
  });

  test('area view: the row wears the back burner state icon inside its area', async () => {
    const host = await mountBody('area', popout);
    const sub = host.querySelector<HTMLElement>('[data-task-manager-area-sub="7:todo"]');
    expect(sub, 'the area keeps a back burner subsection').not.toBeNull();
    expect(sub!.dataset.folded).toBe('on');
    host.querySelector<HTMLElement>('[data-task-manager-area-sub-fold="7:todo"]')!.click();
    await settle();
    const row = host.querySelector<HTMLElement>('[data-huddle-item="3"]')!;
    expect(row.querySelector('[data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('todo');
  });

  test('the row menu parks an open item and takes a parked one off (a PATCH of state, taking off returns to open)', async () => {
    const host = await mountBody('status', popout);
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    openRowMenu(host, 1);
    await settle();
    const park = menuNode('back-burner')!;
    expect(park.textContent).toContain('park');
    park.click();
    await settle();
    expect(server.patches.at(-1)).toEqual({ path: '/cplugs/huddle/items/1', body: { state: 'todo', expected_revision: 1 } });

    host.querySelector<HTMLElement>('[data-task-manager-status-fold="todo"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    openRowMenu(host, 2);
    await settle();
    const off = menuNode('back-burner')!;
    expect(off.textContent).toContain('release');
    off.click();
    await settle();
    expect(server.patches.at(-1)).toEqual({ path: '/cplugs/huddle/items/2', body: { state: 'open', expected_revision: 1 } });
  });
});
