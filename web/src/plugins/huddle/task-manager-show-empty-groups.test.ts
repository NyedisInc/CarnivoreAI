/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ settings: {} as Record<string, unknown>, view: 'area', puts: [] as string[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle') {
        if (init.method === 'PUT') {
          server.puts.push(String(init.body));
          Object.assign(server.settings, JSON.parse(String(init.body)).settings);
        }
        return { revision: 1, settings: { ...server.settings, view: server.view } };
      }
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 },
          { key: '18', name: 'carnivore', project_id: 18, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 },
        ] };
      }
      if (path === '/cplugs/huddle/lists/18?live_only=1') {
        return { list: '18', revision: 1, cursor: 1, groups: [{ id: 3, list: '18', name: 'widgets', position: 0, folded: false }], items: [] };
      }
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

async function open(popout: boolean): Promise<HTMLElement> {
  await refreshPrefs();
  huddle.selected = '18';
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

beforeEach(() => {
  server.settings = {};
  server.puts = [];
  huddle.openId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('show empty groups, by area', () => {
  const view = 'area';
  for (const popout of [false, true]) {
    test(`default off hides the empty group, the key shows it, and it is remembered (${popout ? 'pop-out' : 'sidebar'})`, async () => {
      server.view = view;
      const host = await open(popout);
      const key = host.querySelector<HTMLButtonElement>('[data-task-manager-show-empty-groups]')!;
      expect(key.getAttribute('aria-pressed')).toBe('false');
      expect(key.getAttribute('aria-label')).toBe('show empty groups');
      expect(key.title).toBe('show empty groups');
      expect(host.querySelector('[data-task-manager-section-head="3"]')).toBeNull();

      key.click();
      await settle();
      expect(JSON.parse(server.puts[0] ?? '{}').settings).toEqual({ showEmptyGroups: true });
      expect(taskManagerPrefs.showEmptyGroups).toBe(true);
      expect(host.querySelector('[data-task-manager-show-empty-groups]')!.getAttribute('aria-pressed')).toBe('true');
      expect(host.querySelector('[data-task-manager-show-empty-groups]')!.getAttribute('aria-label')).toBe('hide empty groups');
      expect(host.querySelector('[data-task-manager-section-head="3"]')).not.toBeNull();

      taskManagerPrefs.showEmptyGroups = false;
      await refreshPrefs();
      expect(taskManagerPrefs.showEmptyGroups).toBe(true);
    });
  }
});

describe('show empty groups, by status', () => {
  for (const popout of [false, true]) {
    test(`no group keys in the status view; the stored setting still applies (${popout ? 'pop-out' : 'sidebar'})`, async () => {
      server.view = 'status';
      const hidden = await open(popout);
      expect(hidden.querySelector('[data-task-manager-show-empty-groups]')).toBeNull();
      expect(hidden.querySelector('[data-task-manager-new-group]')).toBeNull();
      expect(hidden.querySelector('[data-task-manager-section-head="3"]')).toBeNull();
      unmount(app!);
      app = null;
      document.body.innerHTML = '';
      server.settings = { showEmptyGroups: true };
      const shown = await open(popout);
      expect(shown.querySelector('[data-task-manager-section-head="3"]')).not.toBeNull();
    });
  }
});
