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
import { resourcePush } from '../sdk';
import { cplugEnablement } from '../host/enablement.svelte';
import { setSectionFolded } from './task-manager-status-folds.svelte';

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

beforeEach(async () => {
  setSectionFolded('none:done', false); // the area view's done subsection starts folded; these tests read checked rows
  server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'area' } };
  server.focus = null;
  server.calls = [];
  huddle.selected = 'all';
  huddle.openId = null;
  taskManagerFocus.focus = null;
  taskManagerFocus.applied = 0;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the sidebar control row is icon keys', () => {
  test('remove completed, hide completed and tell claude are icon buttons with a tooltip and an aria-label', async () => {
    const host = await mountBody(false);
    const row = host.querySelector<HTMLElement>('[data-task-manager-controls]')!;
    const keys = [...row.querySelectorAll<HTMLElement>('[data-task-manager-remove-completed], [data-task-manager-hide-completed], [data-task-manager-send]')];
    expect(keys.map((k) => Object.keys(k.dataset).find((d) => d.startsWith('taskManager')))).toEqual(['taskManagerRemoveCompleted', 'taskManagerHideCompleted', 'taskManagerSend']);
    for (const key of keys) {
      expect(key.classList.contains('oc-ibtn')).toBe(true);
      expect(key.getAttribute('aria-label')).toBeTruthy();
      expect(key.getAttribute('title')).toBeTruthy();
    }
    expect(row.querySelector('.oc-btn, .oc-check')).toBeNull();
    expect(keys[0]!.getAttribute('aria-label')).toBe('remove completed (1)');
    expect(keys[0]!.textContent!.trim()).toBe('1');
    for (const key of keys.slice(1)) expect(key.querySelector('svg')).not.toBeNull();
  });

  test('the eye key is a pressed toggle that stores hide completed', async () => {
    const host = await mountBody(false);
    const eye = host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!;
    expect(eye.getAttribute('aria-pressed')).toBe('false');
    expect(host.querySelectorAll('[data-huddle-item]')).toHaveLength(3);
    eye.click();
    await settle();
    expect(taskManagerPrefs.hideCompleted).toBe(true);
    expect(eye.getAttribute('aria-pressed')).toBe('true');
    expect(host.querySelectorAll('[data-huddle-item]')).toHaveLength(2);
  });

  test('pop-out: hide completed and tell claude are the same footer keys as the sidebar (Joe, 2026-10-05)', async () => {
    const host = await mountBody(true);
    const key = host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!;
    expect(key.classList.contains('hd-key')).toBe(true);
    expect(key.getAttribute('aria-pressed')).toBe('false');
    const tell = host.querySelector('[data-task-manager-controls] [data-task-manager-send]')!;
    expect(tell.classList.contains('hd-key')).toBe(true);
    expect(tell.classList.contains('hd-key--act')).toBe(true);
  });
});

describe('claude points here (huddle_focus)', () => {
  test('compact: a pushed focus highlights its rows, opens one and shows the tab (the badge stays the incomplete count); a touch clears it everywhere', async () => {
    server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'area', density: 'compact' } };
    await refreshPrefs();
    const host = await mountBody(false);
    expect(taskManagerPrefs.density).toBe('compact');
    expect(host.querySelector('[data-task-manager-focused]')).toBeNull();
    server.focus = { seq: 41, list: 'all', items: [2, 3], open: 2 };
    pushFocus();
    await settle();
    const focused = [...host.querySelectorAll<HTMLElement>('[data-task-manager-focused]')].map((r) => r.dataset.huddleItem);
    expect(focused).toEqual(['2', '3']);
    expect(host.querySelector('[data-huddle-item="2"]')?.classList.contains('tkm--focus')).toBe(true);
    expect(host.querySelector('[data-huddle-item="1"]')?.classList.contains('tkm--focus')).toBe(false);
    expect(huddle.openId).toBe(2);
    expect(host.querySelector('[data-task-manager-detail="2"]')).not.toBeNull();
    expect(taskManagerTab.badge).toBeUndefined();

    huddle.openId = null;
    pushFocus();
    await settle();
    expect(huddle.openId).toBeNull();
    expect(host.querySelectorAll('[data-task-manager-focused]')).toHaveLength(2);

    host.querySelector<HTMLElement>('[data-task-manager-body]')!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    await settle();
    expect(host.querySelector('[data-task-manager-focused]')).toBeNull();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/focus' && c.method === 'POST' && (c.body as { clear?: boolean })?.clear)).toBe(true);
    expect(taskManagerTab.badge).toBeUndefined();
  });

  test.each(['normal', 'full'])('%s: a focus highlights and scrolls to the row but never expands it', async (density) => {
    const scrolled: string[] = [];
    const scroll = vi.fn(function (this: HTMLElement) { scrolled.push(this.dataset.huddleItem ?? ''); });
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: scroll, configurable: true, writable: true });
    vi.stubGlobal('requestAnimationFrame', (run: FrameRequestCallback) => { run(0); return 0; });
    try {
      server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'area', density } };
      await refreshPrefs();
      const host = await mountBody(false);
      expect(taskManagerPrefs.density).toBe(density);
      server.focus = { seq: 51, list: 'all', items: [2], open: 2 };
      pushFocus();
      await settle();
      expect(host.querySelector('[data-huddle-item="2"]')?.classList.contains('tkm--focus')).toBe(true);
      expect(huddle.openId).toBeNull();
      expect(host.querySelector('[data-task-manager-detail="2"]')).toBeNull();
      expect(scrolled).toContain('2');
    } finally {
      vi.unstubAllGlobals();
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });
});
