/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: { hideCompleted: false, view: 'area' } as Record<string, unknown> },
  states: { 1: 'open', 2: 'open', 3: 'open' } as Record<number, string>,
  asking: 0,
}));

const mk = (id: number, over: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...over,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle' && (init.method ?? 'GET') === 'PUT') {
        const body = JSON.parse(String(init.body));
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
      const patch = /^\/cplugs\/huddle\/items\/(\d+)$/.exec(path);
      if (patch && init.method === 'PATCH') {
        const body = JSON.parse(String(init.body));
        server.states[Number(patch[1])] = body.approved ? 'done' : 'open';
        return {};
      }
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 2, open: 1, review: 0, questions: 0, claude_seq: 0 }] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 7, cursor: 7, items: [1, 2, 3].map((id) => mk(id, { state: server.states[id], thread: id === server.asking ? [{ id: 90, item_id: id, kind: 'question', answered: false, text: 'which?', author: 'claude', created_at: 1, seq: 90 }] : [] })) };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import { setSectionFolded } from './task-manager-status-folds.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

const openRows = (host: HTMLElement) => [...host.querySelectorAll('[data-huddle-item].tkm--open')].map((el) => el.getAttribute('data-huddle-item'));

beforeEach(async () => {
  setSectionFolded('none:done', false); // the area view's done subsection starts folded; these tests read checked rows
  server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'area' } };
  server.states = { 1: 'open', 2: 'open', 3: 'open' };
  server.asking = 0;
  huddle.selected = 'all';
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('ticking the open item', () => {
  test.each([false, true])('opens no other row (hide completed %s)', async (hide) => {
    server.prefs = { revision: 3, settings: { hideCompleted: hide, view: 'area' } };
    await refreshPrefs();
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(openRows(host)).toEqual(['2']);
    host.querySelector<HTMLElement>('[data-task-manager-check="2"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    expect(openRows(host)).toEqual(hide ? [] : ['2']);
  });

  test('a later row with a waiting question is not opened by the refresh that follows a tick', async () => {
    server.asking = 3;
    await refreshTaskManager();
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(openRows(host)).toEqual(['2']);
    host.querySelector<HTMLElement>('[data-task-manager-check="2"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    expect(openRows(host)).toEqual(['2']);
  });

  test('compact: a question that arrives on a closed row still opens it', async () => {
    server.prefs.settings.density = 'compact'; // a question opens the row only in compact (docs/task-manager.md section 24)
    await refreshPrefs();
    const host = await mountBody();
    expect(openRows(host)).toEqual([]);
    server.asking = 3;
    await refreshTaskManager();
    await settle();
    expect(openRows(host)).toEqual(['3']);
  });

  test('normal: a question that arrives stays on the collapsed row, which shows it and a reply box', async () => {
    const host = await mountBody();
    server.asking = 3;
    await refreshTaskManager();
    await settle();
    expect(openRows(host)).toEqual([]);
    expect(host.querySelector('[data-task-manager-reply-on-row="3"]')).not.toBeNull();
  });
});
