/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { compile } from 'svelte/compiler';

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: unknown }[],
  lights: {} as Record<number, Record<string, boolean>>,
}));

const mk = (id: number) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, status: 'working',
  thread: [{ id: 10 + id, item_id: id, author: 'claude', kind: id === 1 ? 'info' : 'attention', text: id === 1 ? 'the whole info text, never clipped' : 'the whole look text, never clipped',
    answered: false, created_at: 0, seq: 1, unread: (id === 1 && !!server.lights[id]?.info_unseen) || (id === 2 && !!server.lights[id]?.attention_unseen) }],
  unread: false, info_unseen: false, attention_unseen: false, info_unread: server.lights[id]?.info_unseen ? 1 : 0,
  attention_unread: server.lights[id]?.attention_unseen ? 1 : 0, ...server.lights[id],
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: init.body ? JSON.parse(String(init.body)) : null });
      const seen = /^\/cplugs\/huddle\/items\/(\d+)\/seen$/.exec(path);
      if (seen) {
        const id = Number(seen[1]);
        const message = init.body ? (JSON.parse(String(init.body)) as { message?: number }).message : undefined;
        const flag = id === 1 ? 'info_unseen' : 'attention_unseen';
        server.lights[id] = message ? { ...server.lights[id], [flag]: false } : { ...server.lights[id], unread: false };
        return mk(id);
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 1, waiting_to_send: 2 }] };
      }
      if (path.endsWith('/sessions')) return { sessions: [], default: null, reason: 'pick' };
      if (path === '/cplugs/huddle/send') {
        const lists = (JSON.parse(String(init.body)) as { lists: string[] }).lists;
        return { results: lists.map((list) => ({ list, status: 'sent', target: 'ses_1', label: 'agent one' })) };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: [mk(1), mk(2), mk(3)] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { resetSendPicks, sendPicks } from './huddle-send-many.svelte';
import { needsSeen, stripeColor, stripeSignal } from './task-manager-lights';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
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

async function mountBody(popout = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

const writes = (): string[] => server.calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/seen')).map((c) => c.path);

function type(el: HTMLInputElement | HTMLTextAreaElement, text: string): void {
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
}

beforeEach(async () => {
  server.calls = [];
  server.lights = { 1: { info_unseen: true }, 2: { unread: true, attention_unseen: true }, 3: { unread: true } };
  huddle.selected = 'all';
  huddle.addTarget = 'all';
  huddle.openId = null;
  resetSendPicks();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const stripeOf = (host: HTMLElement, id: number): HTMLElement => host.querySelector<HTMLElement>(`[data-huddle-item="${id}"] .tkm-state`)!;

describe('the lights', () => {
  test('pure: attention outranks unread outranks info, any of them needs a seen mark, attention swaps the stripe colour', () => {
    expect(stripeSignal({ unread: true, attention_unseen: true })).toBe('attention');
    expect(stripeSignal({ unread: true })).toBe('unread');
    expect(stripeSignal({ unread: false, info_unseen: true })).toBe('info');
    expect(stripeSignal({ unread: false })).toBeNull();
    expect(needsSeen({ unread: false, info_unseen: true } as never)).toBe(false);
    expect(needsSeen({ unread: false, attention_unseen: true } as never)).toBe(false);
    expect(needsSeen({ unread: false })).toBe(false);
    expect(stripeColor('var(--oc-green)', 'attention')).toBe('var(--oc-cyan)');
    expect(stripeColor('var(--oc-green)', 'unread')).toBe('var(--oc-green)');
    expect(stripeColor('var(--oc-green)', 'info')).toBe('var(--oc-green)');
  });

  test('no lights right of the number: info, attention and unread are signals on the left stripe', async () => {
    const host = await mountBody();
    expect(host.querySelector('.hdr-unread, .hdr-info, [data-huddle-unread], [data-huddle-info], .hdr-line .status-led')).toBeNull();
    const stripe = (id: number) => host.querySelector<HTMLElement>(`[data-huddle-item="${id}"] .tkm-state`)!;
    expect(stripe(1).dataset.taskManagerSignal).toBe('info');
    expect(stripe(1).getAttribute('title')).toContain('claude added info');
    expect(stripe(2).dataset.taskManagerSignal).toBe('attention');
    expect(stripe(2).getAttribute('title')).toContain('claude wants your attention here');
    expect(host.querySelector<HTMLElement>('[data-huddle-item="2"]')!.style.getPropertyValue('--_state')).toBe('var(--oc-cyan)');
    expect(stripe(3).dataset.taskManagerSignal).toBe('unread');
  });

  test('opening an info row reads no info (item 83); the thread still tags it', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/items/1/seen')).toBe(false);
    expect(host.querySelector('[data-hb-kind="info"]')!.textContent).toBe('info');
  });
});

describe('the row post block (items 83 and 87, section 26)', () => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';
    test(`${where}: the main icon is the status; each unread info and look shows in full and its own icon reads that one`, async () => {
      taskManagerPrefs.density = 'normal';
      const host = await mountBody(popout);
      const slot = (id: number) => host.querySelector<HTMLElement>(`[data-huddle-item="${id}"] [data-task-manager-status-icon]`)!;
      expect(slot(1).dataset.taskManagerStatusIcon).toBe('working');
      expect(slot(2).dataset.taskManagerStatusIcon).toBe('working');
      expect(slot(1).innerHTML).toBe(slot(3).innerHTML);
      expect(slot(2).innerHTML).toBe(slot(3).innerHTML);
      expect(host.querySelector('[data-huddle-mark-read]')).toBeNull();
      const info = host.querySelector<HTMLElement>('[data-task-manager-posts="1"]')!;
      expect(info.textContent).toContain('the whole info text, never clipped');
      expect(info.querySelector('[data-task-manager-post-kind]')!.getAttribute('data-task-manager-post-kind')).toBe('info');
      const look = host.querySelector<HTMLElement>('[data-task-manager-posts="2"]')!;
      expect(look.textContent).toContain('the whole look text, never clipped');
      expect(look.querySelector('[data-task-manager-post-kind]')!.getAttribute('data-task-manager-post-kind')).toBe('attention');
      const lookKey = look.querySelector<HTMLElement>('[data-task-manager-post-read="12"]')!;
      const infoKey = info.querySelector<HTMLElement>('[data-task-manager-post-read="11"]')!;
      expect(lookKey.innerHTML).not.toBe(infoKey.innerHTML);
      expect(lookKey.closest<HTMLElement>('[data-task-manager-post]')!.style.getPropertyValue('--_post')).toBe('var(--oc-cyan)');
      expect(infoKey.closest<HTMLElement>('[data-task-manager-post]')!.style.getPropertyValue('--_post')).toBe('var(--oc-violet)');
      expect(lookKey.getAttribute('aria-label')).toBe('mark this look read');
      lookKey.click();
      await settle();
      const reads = server.calls.filter((c) => /\/seen$/.test(c.path));
      expect(reads.map((c) => [c.path, c.body])).toEqual([['/cplugs/huddle/items/2/seen', { message: 12 }]]);
      expect(host.querySelector('[data-task-manager-posts="2"]')).toBeNull();
      expect(host.querySelector('[data-task-manager-posts="1"]')).not.toBeNull();
      expect(slot(2).dataset.taskManagerStatusIcon).toBe('working');
      expect(huddle.openId).toBeNull();
      infoKey.click();
      await settle();
      expect(server.calls.filter((c) => /\/seen$/.test(c.path)).map((c) => c.body)).toEqual([{ message: 12 }, { message: 11 }]);
      expect(host.querySelector('[data-task-manager-posts="1"]')).toBeNull();
    });

    test(`${where}: compact shows only a small count per kind`, async () => {
      taskManagerPrefs.density = 'compact';
      const host = await mountBody(popout);
      expect(host.querySelector('[data-task-manager-posts="1"]')).toBeNull();
      expect(host.querySelector('[data-task-manager-posts="2"]')).toBeNull();
      expect(host.querySelector('[data-huddle-item="1"] [data-task-manager-posts-count="1"]')!.textContent).toBe('1');
      expect(host.querySelector('[data-huddle-item="1"] [data-task-manager-posts-count]')!.getAttribute('data-task-manager-post-kind')).toBe('info');
      const look = host.querySelector<HTMLElement>('[data-huddle-item="2"] [data-task-manager-posts-count="2"]')!;
      expect(look.textContent).toBe('1');
      expect(look.dataset.taskManagerPostKind).toBe('attention');
      taskManagerPrefs.density = 'normal';
    });
  }
});

describe('enter sends and tells claude, nothing queues (Alex (example-owner), 2026-10-05; reverses Joe\'s shift-queue)', () => {
  test('the one-line add box adds, then tells the add box list, on Enter', async () => {
    const host = await mountBody();
    const input = host.querySelector<HTMLInputElement>('input[data-task-manager-add]')!;
    type(input, 'ship it');
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    expect(writes()).toEqual(['/cplugs/huddle/lists/all/inbox', '/cplugs/huddle/send']);
    expect(server.calls.find((c) => c.path === '/cplugs/huddle/send')!.body).toEqual({ lists: ['all'], queue: true });
    expect(input.value).toBe('');
  });

  test('the multiline box sends the whole text as one entry on cmd+enter, then tells; the session picked for that list is used', async () => {
    sendPicks.picks = { all: 'ses_9' };
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-multiline]')!.click();
    await settle();
    const area = host.querySelector<HTMLTextAreaElement>('textarea[data-task-manager-add]')!;
    type(area, 'one\ntwo');
    area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true, cancelable: true }));
    await settle();
    expect(writes()).toEqual(['/cplugs/huddle/lists/all/inbox', '/cplugs/huddle/send']);
    expect(server.calls.find((c) => c.path === '/cplugs/huddle/lists/all/inbox')!.body).toEqual({ text: 'one\ntwo', client_id: expect.any(String) });
    expect(server.calls.find((c) => c.path === '/cplugs/huddle/send')!.body).toEqual({ lists: ['all'], queue: true, targets: { all: 'ses_9' } });
  });

  test('shift changes nothing: a shift-click on the reply key still sends and tells', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    const box = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply="3"]')!;
    type(box, 'now');
    host.querySelector<HTMLButtonElement>('[data-task-manager-actions="3"] .hdt-send')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey: true }));
    await settle();
    expect(writes()).toEqual(['/cplugs/huddle/items/3/messages', '/cplugs/huddle/send']);
    expect(host.textContent).not.toContain('queue');
  });

  test('the reply box replies, then tells the item list, on Enter', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    const box = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply="3"]')!;
    type(box, 'go ahead');
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    expect(writes()).toEqual(['/cplugs/huddle/items/3/messages', '/cplugs/huddle/send']);
    expect(server.calls.find((c) => c.path === '/cplugs/huddle/send')!.body).toEqual({ lists: ['all'], queue: true });
  });
});

describe('a tick tells right away', () => {
  const sendCalls = (): number => server.calls.filter((c) => c.path === '/cplugs/huddle/send').length;
  const patches = (): number => server.calls.filter((c) => c.method === 'PATCH').length;

  test('a plain tick saves the tick, then tells the item list', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-check="3"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    expect(patches()).toBe(1);
    expect(sendCalls()).toBe(1);
  });
});

function specificity(selector: string): number[] {
  const bare = selector.replace(/:where\([^)]*\)/g, '').replace(/::[a-z-]+/g, '');
  const ids = (bare.match(/#[\w-]+/g) ?? []).length;
  const classes = (bare.match(/\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+/g) ?? []).length;
  const types = (bare.replace(/[.#:[][^\s>+~]*/g, ' ').match(/\b[a-z][\w-]*/g) ?? []).length;
  return [ids, classes, types];
}

const outranks = (a: number[], b: number[]): boolean => {
  const i = a.findIndex((n, k) => n !== b[k]);
  return i >= 0 && (a[i] ?? 0) > (b[i] ?? 0);
};

function compiledCss(file: string): string {
  const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), 'utf8');
  return (compile(source, { filename: file, css: 'external' }).css?.code ?? '').replace(/\/\*[\s\S]*?\*\//g, '');
}

function widthRules(file: string): [string, string][] {
  const css = compiledCss(file);
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((m) => [(m[1] ?? '').trim(), m[2] ?? ''] as [string, string])
    .filter(([, body]) => /(^|[;\s])width\s*:/.test(body));
}

describe('the sidebar control row at 300px', () => {
  test('the icon keys set no width of their own; the count key only grows (auto, 24px floor)', async () => {
    expect(compiledCss('./HuddleBody.svelte')).not.toMatch(/hd-key-n/);
    const rules = widthRules('./HuddleBody.svelte').filter(([sel]) => /\.hd-key/.test(sel));
    expect(rules.filter(([sel]) => !/hd-key--count/.test(sel))).toEqual([]);
    expect(rules.length).toBe(1);
    expect(rules[0]![1]).toMatch(/(^|[;\s])width\s*:\s*auto/);
    expect(rules[0]![1]).toMatch(/min-width\s*:\s*var\(--oc-ibtn-size,\s*24px\)/);
  });
});
