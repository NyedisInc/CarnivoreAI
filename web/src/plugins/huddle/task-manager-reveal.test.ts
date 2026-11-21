/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: { hideCompleted: false, view: 'area' } as Record<string, unknown> },
  focus: null as null | { seq: number; list: string; items: number[]; open: number | null },
  calls: [] as { path: string; method: string; body: unknown }[],
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
      const method = init.method ?? 'GET';
      const body = init.body ? JSON.parse(String(init.body)) : null;
      server.calls.push({ path, method, body });
      if (path === '/cplugs/huddle' && method === 'PUT') {
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
      if (path === '/cplugs/huddle/focus') {
        if (method === 'POST' && body?.clear) server.focus = null;
        return { focus: structuredClone(server.focus) };
      }
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 2, review: 0, questions: 0, claude_seq: 0 }] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 7, cursor: 7, items: [mk(1), mk(2), mk(3, { state: 'done' })] };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerFocus } from './task-manager-focus.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import { taskManagerTab } from './task-manager-tab';
import HuddleBody from './HuddleBody.svelte';
import { resourcePush, revealWish } from '../sdk';
import { cplugEnablement } from '../host/enablement.svelte';
import { isFolded, projectFoldKey, sectionFoldKey, setSectionFolded, subFoldKey } from './task-manager-status-folds.svelte';
import { foldsHiding } from './task-manager-reveal';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

/** A `resources.changed` frame naming the focus topic, as the events socket delivers it. */
function pushFocus(): void {
  const store = resourcePush().store;
  store.hello({ resource_topics: ['cplug.huddle.list', 'cplug.huddle.focus'] });
  store.frame({ topics: ['cplug.huddle.focus'] });
}



let scrolled: string[] = [];

beforeEach(async () => {
  scrolled = [];
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: function (this: HTMLElement) { scrolled.push(this.dataset.huddleItem ?? ''); }, configurable: true, writable: true });
  vi.stubGlobal('requestAnimationFrame', (run: FrameRequestCallback) => { run(0); return 0; });
  server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
  server.focus = null;
  server.calls = [];
  huddle.selected = 'all';
  huddle.openId = null;
  taskManagerFocus.focus = null;
  taskManagerFocus.applied = 0;
  revealWish.id = null;
  setSectionFolded(sectionFoldKey('all', 'open'), false);
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('the fold that hides a focused item opens', () => {
  test('status view: a folded section opens, the row is drawn and scrolled to; Claude\'s pointing in normal density does not expand it', async () => {
    setSectionFolded(sectionFoldKey('all', 'open'), true);
    const host = await mountBody();
    expect(host.querySelector('[data-huddle-item="2"]')).toBeNull();
    server.focus = { seq: 61, list: 'all', items: [2], open: 2 };
    pushFocus();
    await settle();
    expect(isFolded(sectionFoldKey('all', 'open'))).toBe(false);
    expect(host.querySelector('[data-huddle-item="2"]')).not.toBeNull();
    expect(scrolled).toContain('2');
    expect(huddle.openId).toBeNull();
  });

  test('a local open in task manager press (the reveal wish) also opens the row, whatever the density', async () => {
    setSectionFolded(sectionFoldKey('all', 'open'), true);
    const host = await mountBody();
    revealWish.id = 2;
    server.focus = { seq: 62, list: 'all', items: [2], open: 2 };
    pushFocus();
    await settle();
    expect(huddle.openId).toBe(2);
    expect(revealWish.id).toBeNull();
    expect(host.querySelector('[data-task-manager-detail="2"]')).not.toBeNull();
  });

  test('a section that is already open is not written, and a re-read of the same focus does not move the view again', async () => {
    const host = await mountBody();
    server.focus = { seq: 63, list: 'all', items: [2], open: 2 };
    pushFocus();
    await settle();
    expect(host.querySelector('[data-huddle-item="2"]')).not.toBeNull();
    const first = scrolled.length;
    pushFocus();
    await settle();
    expect(scrolled.length).toBe(first);
  });
});

describe('foldsHiding names every fold between the top and the row, for the view on screen', () => {
  const it = (id: number, over: Record<string, unknown> = {}) => mk(id, over) as never;
  const grp = { id: 4, list: 'all', name: 'webhooks', position: 1, folded: true };

  test('status view: the project bar, the item\'s section, and its area under that section when the list has named groups', () => {
    const item = it(2, { group: 4 });
    expect(foldsHiding('status', '12', item, [it(1), item], [], false).keys).toEqual([projectFoldKey('12'), '12/open']);
    expect(foldsHiding('status', '12', item, [it(1), item], [grp], false).keys).toEqual([projectFoldKey('12'), '12/open', 'status/4:open']);
  });

  test('area view: the project bar, the item\'s named group (a server fold) and its status subsection inside it', () => {
    const item = it(2, { group: 4 });
    const got = foldsHiding('area', '12', item, [it(1), item], [grp], false);
    expect(got.keys).toEqual([projectFoldKey('12'), subFoldKey(4, 'open')]);
    expect(got.groups).toEqual([grp]);
    expect(foldsHiding('area', '12', it(1), [it(1), item], [grp], false).keys).toEqual([projectFoldKey('12'), subFoldKey(null, 'open')]);
  });
});
