/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', status: 'open', section: 'open', kind: '', number: id,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, ...extra,
});
const DONE = (id: number) => mk(id, { state: 'done', status: 'done', section: 'done', number: null, text: `finished ${id}` });
const ALL_DONE = Array.from({ length: 120 }, (_, n) => 1000 + n);

const server = vi.hoisted(() => ({ reads: [] as string[], done: [] as string[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: {} };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '12', name: 'alpha', project_id: 12, items: 6, open: 1, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) {
        server.reads.push(path);
        return { cursor: 9, groups: [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], done_count: ALL_DONE.length, items: [mk(1)] }] };
      }
      if (path.startsWith('/cplugs/huddle/lists/12/done')) {
        server.done.push(path);
        const q = new URLSearchParams(path.split('?')[1]);
        const offset = Number(q.get('offset')), limit = Number(q.get('limit'));
        const page = ALL_DONE.slice(offset, offset + limit);
        return { list: '12', total: ALL_DONE.length, offset, next_offset: offset + limit < ALL_DONE.length ? offset + limit : null,
          items: page.map((id) => ({ ...DONE(id), thread_count: 0, thread_slim: true })) };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';
import { DONE_PAGE, doneStore } from './task-manager-done.svelte';
import { setSectionFolded, sectionFoldKey } from './task-manager-status-folds.svelte';
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

const pastCoalesce = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 400));
  await settle();
};

beforeEach(() => {
  server.reads = [];
  server.done = [];
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  doneStore.pages = {};
  setSectionFolded(sectionFoldKey('12', 'done'), true);
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const mountBody = async (): Promise<HTMLElement> => {
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
};
const doneCount = (host: HTMLElement): string | undefined => host.querySelector('[data-task-manager-status-count="done"]')?.textContent?.trim();
const doneRows = (host: HTMLElement): number => host.querySelectorAll('[data-task-manager-status-section="done"] [data-huddle-item]').length;

describe('the done section', () => {
  test('shows its count from the live read and fetches nothing while it is folded', async () => {
    const host = await mountBody();
    expect(server.reads[0]).toBe('/cplugs/huddle/aggregate?live_only=1');
    expect(doneCount(host)).toBe(String(ALL_DONE.length));
    expect(doneRows(host)).toBe(0);
    expect(server.done).toEqual([]);
    await refreshTaskManager();
    await settle();
    expect(server.done).toEqual([]);
  });

  test('opening it fetches the first page only, and load more reads the next', async () => {
    const host = await mountBody();
    setSectionFolded(sectionFoldKey('12', 'done'), false);
    await settle();
    expect(server.done).toEqual([`/cplugs/huddle/lists/12/done?limit=${DONE_PAGE}&offset=0`]);
    expect(doneRows(host)).toBe(DONE_PAGE);
    expect(doneCount(host)).toBe(String(ALL_DONE.length));
    const more = host.querySelector<HTMLButtonElement>('[data-task-manager-done-more]');
    expect(more?.textContent?.trim()).toBe(`load ${ALL_DONE.length - DONE_PAGE} more`);
    more!.click();
    await settle();
    expect(server.done.at(-1)).toBe(`/cplugs/huddle/lists/12/done?limit=${DONE_PAGE}&offset=${DONE_PAGE}`);
    expect(doneRows(host)).toBe(DONE_PAGE * 2);
    expect(huddle.groups![0]!.items.map((i) => i.id).slice(0, 3)).toEqual([1, 1000, 1001]);
  });

  test('a push re-reads the done rows while the section is open, and closing it drops them', async () => {
    const host = await mountBody();
    setSectionFolded(sectionFoldKey('12', 'done'), false);
    await settle();
    server.done = [];
    await refreshTaskManager();
    await settle();
    expect(server.done).toEqual([`/cplugs/huddle/lists/12/done?limit=${DONE_PAGE}&offset=0`]);
    expect(doneRows(host)).toBe(DONE_PAGE);
    setSectionFolded(sectionFoldKey('12', 'done'), true);
    await settle();
    expect(huddle.groups![0]!.items.map((i) => i.id)).toEqual([1]);
    server.done = [];
    await refreshTaskManager();
    await settle();
    expect(server.done).toEqual([]);
    expect(doneCount(host)).toBe(String(ALL_DONE.length));
    await pastCoalesce();
  });
});
