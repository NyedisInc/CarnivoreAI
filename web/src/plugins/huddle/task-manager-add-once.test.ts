/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ posts: 0, release: null as null | (() => void) }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (path === '/cplugs/huddle' && method !== 'PUT') return { revision: 1, settings: { view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 }] };
      if (/\/inbox$/.test(path) && method === 'POST') {
        server.posts += 1;
        await new Promise<void>((resolve) => { server.release = resolve; });
        return { queued: false, item: { id: 1 } };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 1, cursor: 1, items: [] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
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

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the add box', () => {
  test('two submits before the first POST answers file one item', async () => {
    await refreshPrefs();
    await refreshTaskManager();
    huddle.selected = 'all';
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-add]')!;
    input.value = 'file this once';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    const form = host.querySelector<HTMLFormElement>('form.hd-add')!;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    expect(server.posts).toBe(1);
    server.release?.();
    await settle();
  });
});
