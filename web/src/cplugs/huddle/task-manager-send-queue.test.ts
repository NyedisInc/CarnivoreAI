/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as { path: string; body: unknown }[], flushed: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/cplugs/huddle/send-queue/flush') {
        const lists = (JSON.parse(String(init.body)) as { lists: string[] }).lists;
        return { results: lists.map((list) => ({ list, status: 'sent', target: 'ses_1' })), queue: { now: 1000, quiet_s: 8, cap_s: 30, count: 0, first_at: null, reset_at: null, due_at: null, lists: {} } };
      }
      if (path === '/cplugs/huddle/send') {
        const body = JSON.parse(String(init.body)) as { lists: string[]; queue?: boolean };
        return { results: body.lists.map((list) => ({ list, status: body.queue ? 'queued' : 'sent' })) };
      }
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, waiting_to_send: 0 }] };
      return {};
    },
  };
});

import { huddle } from './huddle.svelte';
import { applyQueue, fillProgress, queueSummary, queuedKeys, resetSendQueue, type SendQueueState } from './task-manager-send-queue.svelte';
import { resetSendPicks } from './huddle-send-many.svelte';
import { submitNow } from './task-submit';
import TaskManagerSend from './TaskManagerSend.svelte';

const NOW = 1000;

const state = (resetAt: number, count = 2, dueAt = resetAt + 8): SendQueueState => ({
  now: NOW, quiet_s: 8, cap_s: 30, count, first_at: resetAt - 3, reset_at: resetAt, due_at: dueAt,
  lists: { all: { count, first_at: resetAt - 3, last_at: resetAt, due_at: dueAt } },
});

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountKey(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerSend, { target: host });
  await settle();
  return host;
}

const key = (host: HTMLElement): HTMLButtonElement => host.querySelector<HTMLButtonElement>('[data-task-manager-send]')!;
const fill = (host: HTMLElement): HTMLElement | null => host.querySelector<HTMLElement>('[data-task-manager-send-fill]');

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
  vi.setSystemTime(NOW * 1000);
  server.calls = [];
  huddle.selected = 'all';
  huddle.lists = [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, waiting_to_send: 0 } as never];
  resetSendPicks();
  resetSendQueue();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetSendQueue();
  vi.useRealTimers();
});

describe('the pure fill', () => {
  test('progress runs from the newest change to the send, clamped, on the server clock', () => {
    const summary = { count: 1, resetAt: 100, dueAt: 108 };
    expect(fillProgress(summary, 102_000, 0)).toEqual({ fraction: 0.25, durationS: 8, elapsedS: 2 });
    expect(fillProgress(summary, 99_000, 0).fraction).toBe(0);
    expect(fillProgress(summary, 500_000, 0).fraction).toBe(1);
    expect(fillProgress(summary, 90_000, 12_000).elapsedS).toBe(2);
  });

  test('a view covers its own list, or every queued list from all projects', () => {
    const queued: SendQueueState = { ...state(100), lists: { '12': { count: 2, first_at: 95, last_at: 100, due_at: 108 }, '18': { count: 1, first_at: 99, last_at: 101, due_at: 109 } } };
    expect(queueSummary(queued, '12')).toEqual({ count: 2, resetAt: 100, dueAt: 108 });
    expect(queueSummary(queued, 'aggregate')).toEqual({ count: 3, resetAt: 101, dueAt: 108 });
    expect(queueSummary(queued, '77')).toBeNull();
    expect(queueSummary(null, 'aggregate')).toBeNull();
    expect(queuedKeys(queued, 'aggregate')).toEqual(['12', '18']);
    expect(queuedKeys(queued, '12')).toEqual(['12']);
  });
});

describe('the key', () => {
  test('nothing queued: no fill, no badge, disabled, as before', async () => {
    const host = await mountKey();
    expect(fill(host)).toBeNull();
    expect(key(host).disabled).toBe(true);
    expect(host.querySelector('[data-task-manager-send-badge]')).toBeNull();
  });

  test('queued changes fill the key from the newest change to due_at, count them and name the click', async () => {
    const host = await mountKey();
    applyQueue(state(NOW - 2));
    await settle();
    const bar = fill(host)!;
    expect(bar.style.getPropertyValue('--hdtl-dur')).toBe('8s');
    expect(bar.style.getPropertyValue('--hdtl-delay')).toBe('-2s');
    expect(Number(bar.style.getPropertyValue('--hdtl-p'))).toBeCloseTo(0.25);
    expect(bar.dataset.taskManagerSendFillDue).toBe(String(NOW + 6));
    expect(host.querySelector('[data-task-manager-send-badge]')!.textContent).toBe('2');
    expect(key(host).disabled).toBe(false);
    expect(key(host).getAttribute('aria-label')).toBe('2 changes queued, they go out when it quiets down: click to send now');
  });

  test('a new change restarts the fill: a fresh bar from the new reset', async () => {
    const host = await mountKey();
    applyQueue(state(NOW - 2));
    await settle();
    const before = fill(host)!;
    applyQueue(state(NOW, 3));
    await settle();
    const after = fill(host)!;
    expect(after).not.toBe(before);
    expect(after.style.getPropertyValue('--hdtl-delay')).toBe('-0s');
    expect(Number(after.style.getPropertyValue('--hdtl-p'))).toBe(0);
    expect(host.querySelector('[data-task-manager-send-badge]')!.textContent).toBe('3');
  });

  test('a click sends now: the flush route is called for the queued lists and the fill clears', async () => {
    const host = await mountKey();
    applyQueue(state(NOW - 2));
    await settle();
    key(host).click();
    await settle();
    const flush = server.calls.find((c) => c.path === '/cplugs/huddle/send-queue/flush')!;
    expect(flush.body).toEqual({ lists: ['all'] });
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/send')).toBe(false);
    expect(fill(host)).toBeNull();
    expect(host.querySelector('[data-task-manager-send-badge]')).toBeNull();
  });

  test('the fill is a static partial bar under reduced motion: the stylesheet turns the animation off', () => {
    const source = readStyles();
    expect(source).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*{\s*\.hdtl-fill\s*{\s*animation: none;/);
    expect(source).toContain('transform: scaleX(var(--hdtl-p, 0))');
  });
});

describe('what is queued and what is not', () => {
  test('a plain change and an answer are both queued; only an explicit immediate bypasses the outbox', async () => {
    await submitNow('all', async () => true);
    await submitNow('all', async () => true);
    await submitNow('all', async () => true, { immediate: true });
    const tells = server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => c.body);
    expect(tells).toEqual([{ lists: ['all'], queue: true }, { lists: ['all'], queue: true }, { lists: ['all'], targets: {} }]);
  });
});

function readStyles(): string {
  return readFileSync('src/cplugs/huddle/TaskManagerSend.svelte', 'utf8') // vitest runs from web/;
}
