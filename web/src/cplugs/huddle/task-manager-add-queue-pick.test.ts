/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ inbox: 0, sends: [] as unknown[], hangSend: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (path === '/cplugs/huddle' && method !== 'PUT') return { revision: 1, settings: { view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 }] };
      if (/\/inbox$/.test(path) && method === 'POST') { server.inbox += 1; return { queued: false, item: { id: server.inbox } }; }
      if (path === '/cplugs/huddle/send') {
        server.sends.push(JSON.parse(String(init.body)));
        if (server.hangSend) await new Promise<void>(() => {});
        return { results: [{ list: 'all', status: 'queued' }] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 1, cursor: 1, items: [] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { sendLists, pickFor, resetSendPicks } from './huddle-send-many.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import { BODY_OPTIONS } from './task-manager-body-options';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  server.inbox = 0; server.sends = []; server.hangSend = false;
  resetSendPicks();
});

async function mountBody(): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  huddle.selected = 'all';
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false }, context: new Map([[BODY_OPTIONS, { sendInAddRow: true }]]) });
  await settle();
  return host;
}

async function submit(host: HTMLElement, text: string): Promise<void> {
  const input = host.querySelector<HTMLInputElement>('[data-task-manager-add]')!;
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  host.querySelector<HTMLFormElement>('form.hd-add')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await settle();
}

describe('add box queue (#2677)', () => {
  test('a queued send keeps queueing when a session is picked and carries the pick', async () => {
    pickFor('all', 'ses_picked');
    await sendLists(['all'], { queue: true });
    expect(server.sends).toEqual([{ lists: ['all'], queue: true, targets: { all: 'ses_picked' } }]);
  });

  test('the Mk2 add form draws no submit button of its own (a hidden one showed as a stray button, #2677)', async () => {
    const host = await mountBody();
    expect(host.querySelector('form.hd-add button[type="submit"]')).toBeNull();
    expect(host.querySelector('form.hd-add [data-btn="hidden-submit"]')).toBeNull();
  });

  test('Enter in the add box submits the form and files the task', async () => {
    const host = await mountBody();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-add]')!;
    input.value = 'from enter';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    input.dispatchEvent(enter);
    await settle();
    expect(enter.defaultPrevented).toBe(true);
    expect(server.inbox).toBe(1);
  });

  test('a tell that never answers does not leave the add box dead', async () => {
    server.hangSend = true;
    const host = await mountBody();
    await submit(host, 'first');
    await submit(host, 'second');
    expect(server.inbox).toBe(2);
  });
});
