/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { menuNode, openRowMenu } from './row-menu-driver.test.helper';

const server = vi.hoisted(() => ({
  items: [] as Record<string, unknown>[],
  settings: {} as Record<string, unknown>,
  calls: [] as { path: string; method: string; body: Record<string, unknown> | null }[],
}));

const msg = (id: number, author: string, kind: string, text: string) => ({
  id, item_id: 0, author, kind, text, answered: false, created_at: 1_700_000_000 + id, seq: id,
});

const mk = (id: number, extra: Record<string, unknown>) => ({
  id, list: 'all', text: `the long description of item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, status: 'open', thread: [],
  unread: false, info_unseen: false, attention_unseen: false, ...extra,
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
        server.settings = { ...server.settings, ...body.settings };
        return { revision: 2, settings: server.settings };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: server.settings };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 6, open: 6, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0 }] };
      if (path.endsWith('/sessions')) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import { densityFrom, focusOpens, latestMessage, replyBoxShows, rowParts, rowTitle } from './huddle-density';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import { resetSendPicks } from './huddle-send-many.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
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

async function useDensity(density: string | undefined): Promise<void> {
  server.settings = density ? { density } : {};
  await refreshPrefs();
}

const ids = (host: HTMLElement, attr: string): string[] =>
  [...host.querySelectorAll<HTMLElement>(`[${attr}]`)].map((el) => el.getAttribute(attr)!).sort();

beforeEach(async () => {
  server.items = [
    mk(1, { title: 'short one', thread: [msg(1, 'claude', 'info', 'fyi: built the thing')] }),
    mk(2, { created_by: 'claude', status: 'question', thread: [msg(2, 'claude', 'question', 'which colour do you want?')] }),
    mk(3, { thread: [msg(3, 'claude', 'info', 'done'), msg(4, 'joe', 'reply', 'thanks, looks good')] }),
    mk(4, { thread: [msg(5, 'claude', 'attention', 'look at this')] }),
    mk(5, { status: 'review', state: 'review', review_description: 'check the row' }),
    mk(6, {}),
  ];
  server.calls = [];
  resetSendPicks();
  huddle.selected = 'all';
  huddle.addTarget = 'all';
  huddle.openId = null;
  await useDensity(undefined);
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('pure rules', () => {
  test('the title falls back to the text; the density defaults to normal; only compact opens on a focus', () => {
    expect(rowTitle({ title: 'short', text: 'long' })).toBe('short');
    expect(rowTitle({ title: '  ', text: 'long' })).toBe('long');
    expect(rowTitle({ title: null, text: 'long' })).toBe('long');
    expect(densityFrom(undefined)).toBe('normal');
    expect(densityFrom({ density: 'full' })).toBe('full');
    expect(densityFrom({ density: 'huge' })).toBe('normal');
    expect([focusOpens('compact'), focusOpens('normal'), focusOpens('full')]).toEqual([true, false, false]);
  });

  test('the latest message is the newest; the reply box is for status question or review only', () => {
    const items = server.items as never[];
    expect(latestMessage(items[2]!)?.text).toBe('thanks, looks good');
    expect(latestMessage(items[5]!)).toBeNull();
    expect(items.map((item) => replyBoxShows(item))).toEqual([false, true, false, false, true, false]);
    expect(rowParts('compact', items[0]!)).toEqual({ extras: false, description: false, latest: false, questions: false, reply: false, review: false, posts: null });
    expect(rowParts('compact', items[1]!)).toEqual({ extras: false, description: false, latest: true, questions: false, reply: false, review: false, posts: null });
    expect(rowParts('normal', items[1]!)).toEqual({ extras: true, description: false, latest: false, questions: true, reply: true, review: true, posts: null });
    expect(rowParts('normal', items[2]!).latest).toBe(false);
    expect(rowParts('full', items[2]!).latest).toBe(false);
    expect(rowParts('normal', items[0]!).reply).toBe(false);
    expect(replyBoxShows({ ...(items[0] as unknown as object), status: 'working' } as never)).toBe(false);
    expect(replyBoxShows({ ...(items[0] as unknown as object), status: 'waiting' } as never)).toBe(false);
    expect(rowParts('full', items[0]!).description).toBe(true);
  });
});

describe('the row at each density', () => {
  test.each([false, true])('normal (the default): title with no second line, reply box where it applies, review card (popout %s)', async (popout) => {
    expect(taskManagerPrefs.density).toBe('normal');
    const host = await mountBody(popout);
    expect(host.querySelector('[data-task-manager-row-title="1"]')!.textContent).toBe('short one');
    expect(host.querySelector('[data-task-manager-row-title="2"]')!.textContent).toBe('the long description of item 2');
    expect(ids(host, 'data-task-manager-latest')).toEqual([]);
    expect(ids(host, 'data-task-manager-reply-on-row')).toEqual(['2', '5']);
    expect(ids(host, 'data-task-manager-review')).toEqual(['5']);
    expect(ids(host, 'data-task-manager-peek-description')).toEqual([]);
    expect(host.querySelector('[data-task-manager-row-title="1"]')!.classList.contains(popout ? 'tkm-text--clip2' : 'tkm-text--clip')).toBe(true);
    expect(huddle.openId).toBeNull();
    expect(host.querySelector('[data-task-manager-detail]')).toBeNull();
  });

  test.each([false, true])('compact: one line of grip, check, status mark and title only (popout %s)', async (popout) => {
    await useDensity('compact');
    const host = await mountBody(popout);
    expect(host.querySelector('[data-task-manager-row-title="1"]')!.textContent).toBe('short one');
    expect(host.querySelector('[data-task-manager-row-title="1"]')!.classList.contains('tkm-text--clip')).toBe(true);
    for (const attr of ['data-task-manager-latest', 'data-task-manager-reply-on-row', 'data-task-manager-review', 'data-task-manager-peek', 'data-task-manager-by-joe', 'data-task-manager-by-claude']) {
      expect(ids(host, attr), attr).toEqual([]);
    }
    const row = host.querySelector<HTMLElement>('[data-huddle-item="1"]')!;
    expect(row.querySelector('[data-task-manager-grip]')).not.toBeNull();
    expect(row.querySelector('[data-task-manager-check]')).not.toBeNull();
    expect(row.querySelector('[data-task-manager-status-icon]')).not.toBeNull();
    expect(row.querySelector('.tkm-count')).toBeNull();
  });

  test.each([false, true])('compact: a waiting question shows its text on one line under the title, no reply box (popout %s)', async (popout) => {
    await useDensity('compact');
    const host = await mountBody(popout);
    huddle.openId = null;
    await settle();
    expect(ids(host, 'data-task-manager-latest')).toEqual(['2']);
    expect(host.querySelector('[data-task-manager-latest="2"]')!.textContent).toContain('which colour do you want?');
    expect(ids(host, 'data-task-manager-reply-on-row')).toEqual([]);
  });

  test.each([false, true])('a question already waiting at load opens once the stored compact density arrives (popout %s)', async (popout) => {
    taskManagerPrefs.loaded = false;
    taskManagerPrefs.density = 'normal';
    const host = await mountBody(popout);
    expect(huddle.openId).toBeNull();
    await useDensity('compact');
    await settle();
    expect(huddle.openId).toBe(2);
    expect(host.querySelector('[data-task-manager-detail]')).not.toBeNull();
  });

  test('a question already waiting at load does not open when the stored density is normal', async () => {
    taskManagerPrefs.loaded = false;
    taskManagerPrefs.density = 'normal';
    await mountBody();
    await useDensity('normal');
    await settle();
    expect(huddle.openId).toBeNull();
  });

  test('full: the description too, plus everything normal shows, with nothing opened', async () => {
    await useDensity('full');
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-peek-description="1"]')!.textContent).toBe('the long description of item 1');
    expect(host.querySelector('[data-task-manager-peek-description="2"]')).toBeNull();
    const line = host.querySelector('[data-task-manager-row-title="2"]')!;
    expect(line.classList.contains('tkm-text--clip') || line.classList.contains('tkm-text--clip2')).toBe(false);
    expect(ids(host, 'data-task-manager-latest')).toEqual([]);
    expect(ids(host, 'data-task-manager-reply-on-row')).toEqual(['2', '5']);
    expect(ids(host, 'data-task-manager-review')).toEqual(['5']);
    expect(huddle.openId).toBeNull();
  });

  test('the switch on the list bar stores the density and the rows follow', async () => {
    const host = await mountBody();
    const keys = [...host.querySelectorAll<HTMLElement>('.hd-bar [data-huddle-density-key]')];
    expect(keys.map((k) => k.dataset.huddleDensityKey)).toEqual(['compact', 'normal', 'full']);
    expect(keys.map((k) => k.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);
    for (const key of keys) expect(key.getAttribute('aria-label') && key.getAttribute('title')).toBeTruthy();
    keys[0]!.click();
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle' && c.method === 'PUT' && (c.body?.settings as Record<string, unknown>)?.density === 'compact')).toBe(true);
    expect(taskManagerPrefs.density).toBe('compact');
    expect(ids(host, 'data-task-manager-latest')).toEqual(['2']);
  });
});

describe('the latest-message line', () => {
  test('one line, ellipsised, its author marked and named (compact: normal and full show an open question in full instead)', async () => {
    await useDensity('compact');
    const host = await mountBody();
    huddle.openId = null;
    await settle();
    const claude = host.querySelector<HTMLElement>('[data-task-manager-latest="2"]')!;
    expect(claude.dataset.by).toBe('claude');
    expect(claude.querySelector('.tkm-latest-text')!.textContent).toBe('which colour do you want?');
    expect(claude.querySelector('.tkm-latest-by')!.getAttribute('aria-label')).toBe('claude');
    await useDensity('normal');
    await settle();
    expect(host.querySelector('[data-task-manager-latest="3"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-latest="1"]')).toBeNull();
    await useDensity('full');
    await settle();
    expect(host.querySelector('[data-task-manager-latest]')).toBeNull();
    expect(host.querySelector('[data-task-manager-latest="6"]')).toBeNull();
  });
});

describe('the reply box on the row', () => {
  test('only when the item is in question or review, never open or working; Enter posts the reply on that item', async () => {
    const host = await mountBody();
    expect(ids(host, 'data-task-manager-reply-on-row')).toEqual(['2', '5']);
    const review = host.querySelector('[data-task-manager-review="5"]')!;
    const reply = host.querySelector('[data-task-manager-reply-on-row="5"]')!;
    expect(review.compareDocumentPosition(reply) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const id of ['1', '3', '4', '6']) expect(host.querySelector(`[data-task-manager-reply-on-row="${id}"]`)).toBeNull();
    const box = host.querySelector<HTMLTextAreaElement>('[data-task-manager-reply-on-row="2"] [data-huddle-reply="2"]')!;
    box.value = 'blue';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/items/2/messages' && c.method === 'POST' && c.body?.text === 'blue')).toBe(true);
    expect(server.calls.filter((c) => c.path.endsWith('/sessions')).length).toBe(0);
  });
});

describe('the title editor', () => {
  test('the open item edits its title and a blank one clears it', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-title="2"]')).toBeNull();
    openRowMenu(host, 2);
    await settle();
    menuNode('title')!.click();
    await settle();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-title-input="2"]')!;
    expect(input.maxLength).toBe(120);
    input.value = 'pick a colour';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    host.querySelector<HTMLElement>('[data-task-manager-title-save="2"]')!.click();
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/items/2' && c.method === 'PATCH' && c.body?.title === 'pick a colour')).toBe(true);
  });
});
