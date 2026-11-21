/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ groups: [] as { id: number; list: string; name: string; position: number; folded: boolean }[], view: 'area', calls: [] as string[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push(`${method} ${path}`);
      const removed = /^\/cplugs\/huddle\/groups\/(\d+)$/.exec(path);
      if (removed && method === 'DELETE') {
        server.groups = server.groups.filter((g) => g.id !== Number(removed[1]));
        return { group: Number(removed[1]), list: '18', ungrouped: [] };
      }
      const made = /^\/cplugs\/huddle\/lists\/([^/]+)\/groups$/.exec(path);
      if (made && method === 'POST') {
        const group = { id: server.groups.length + 3, list: made[1] ?? '', name: JSON.parse(String(init.body)).name, position: server.groups.length, folded: false };
        server.groups.push(group);
        return { ...group, created: true };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, showEmptyGroups: true, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 },
          { key: '18', name: 'carnivore', project_id: 18, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 },
        ] };
      }
      const of18 = () => server.groups.filter((g) => g.list === '18');
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 1, groups: of18().length ? [{ list: '18', name: 'carnivore', project_id: 18, revision: 1, groups: of18(), items: [] }] : [] };
      }
      if (path === '/cplugs/huddle/lists/18?live_only=1') return { list: '18', revision: 1, cursor: 1, groups: of18(), items: [] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
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

async function makeGroup(popout: boolean, name: string, view: string): Promise<HTMLElement> {
  server.view = 'area';
  await refreshPrefs();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  host.querySelector<HTMLElement>('[data-task-manager-new-group]')!.click();
  await settle();
  const input = host.querySelector<HTMLInputElement>('[data-task-manager-group-name]')!;
  input.value = name;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await settle();
  server.view = view;
  await refreshPrefs();
  await settle();
  expect(taskManagerPrefs.view).toBe(view);
  return host;
}

const heads = (host: HTMLElement): string[] =>
  [...host.querySelectorAll<HTMLElement>('[data-task-manager-section-head]')].map((h) => h.textContent?.trim() ?? '');

beforeEach(async () => {
  server.groups = [];
  server.calls = [];
  huddle.openId = null;
  huddle.addTarget = '18';
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe.each([['by area', 'area'], ['by status', 'status']])('a new empty group is drawn, %s', (_name, view) => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';
    for (const selected of ['aggregate', '18']) {
      test(`${selected === '18' ? "in the list's own view" : 'in "all projects", a list with no items'} (${where})`, async () => {
        huddle.selected = selected;
        await refreshTaskManager();
        const host = await makeGroup(popout, 'widgets', view);
        expect(server.groups.map((g) => g.name)).toEqual(['widgets']);
        expect(heads(host).some((h) => h.includes('widgets'))).toBe(true);
        expect(host.querySelector('[data-task-manager-group-empty]')?.textContent).toContain('empty');
        expect(host.querySelector('[data-task-manager-empty]')).toBeNull();
      });
    }

    test(`an empty group can be removed with its key: DELETE /groups/{id}, then it is gone (${where})`, async () => {
      huddle.selected = '18';
      await refreshTaskManager();
      const host = await makeGroup(popout, 'widgets', view);
      const id = server.groups[0]!.id;
      host.querySelector<HTMLElement>(`[data-task-manager-group-remove="${id}"]`)!.click();
      await settle();
      expect(server.calls).toContain(`DELETE /cplugs/huddle/groups/${id}`);
      expect(server.groups).toEqual([]);
      expect(host.querySelector('[data-task-manager-group-empty]')).toBeNull();
    });
  }
});
