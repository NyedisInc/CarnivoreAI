/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'review', section: 'review', ...extra,
});

const server = vi.hoisted(() => ({ patches: [] as Record<string, unknown>[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (_path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH') server.patches.push(JSON.parse(String(init.body)) as Record<string, unknown>);
      return {};
    },
  };
});
vi.mock('./huddle-send-many.svelte', () => ({ sendLists: async () => true }));

import { ApiError } from '../../opscenter/api/auth.svelte';
import { explain, huddle } from './huddle.svelte';
import { lockFromPayload, lockReason, tickLockOf } from './review-lock';
import { closeTickConfirm, tickConfirm, tickItem } from './task-manager-tick-confirm.svelte';
import TaskManagerTickConfirm from './TaskManagerTickConfirm.svelte';
import { t } from '../sdk';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  closeTickConfirm();
  server.patches.length = 0;
  huddle.notice = '';
  huddle.body = null;
  document.body.innerHTML = '';
});

function onScreen(items: ReturnType<typeof mk>[]): void {
  huddle.body = { list: 'all', items } as never;
}

describe('review lock', () => {
  test('a parent with a subtask not done is not ticked: the notice names it and nothing is sent', async () => {
    app = mount(TaskManagerTickConfirm, { target: document.body });
    await tick();
    const parent = mk(1);
    onScreen([parent, mk(2, { forked_from: 1, title: 'wire the route', state: 'review' })]);
    expect(await tickItem(parent as never, true)).toBe(false);
    flushSync();
    expect(huddle.notice).toBe("locked: subtasks not done (1): 'wire the route' (review).");
    expect(tickConfirm.open).toBe(false);
    expect(document.querySelector('[data-task-manager-tick-confirm]')).toBeNull();
    expect(server.patches).toHaveLength(0);
  });

  test('a live hold locks the tick and is named; a stale one does not', () => {
    const held = mk(1, { state: 'waiting', blockers: [{ id: 5, kind: 'children', text: 'its forked tasks', created_by: 'x', created_at: 0, holding: 1 }] });
    expect(lockReason(tickLockOf(held as never, [held as never])!, t)).toBe('locked: still waiting on its forked tasks.');
    const stale = mk(2, { blockers: [{ id: 6, kind: 'children', text: 'its forked tasks', created_by: 'x', created_at: 0, holding: 0 }] });
    expect(tickLockOf(stale as never, [stale as never])).toBeNull();
  });

  test('done, deleted and other lists\' subtasks do not lock; an untick never does', async () => {
    const parent = mk(1);
    onScreen([parent, mk(2, { forked_from: 1, state: 'done' }), mk(3, { forked_from: 1, deleted: true }), mk(4, { forked_from: 9 })]);
    expect(tickLockOf(parent as never, huddle.body!.items)).toBeNull();
    onScreen([parent, mk(5, { forked_from: 1 })]);
    await tickItem(mk(1, { state: 'done' }) as never, false);
    expect(server.patches[0]).toMatchObject({ approved: false });
  });

  test('a server lock refusal is explained from its blocking, in the same words', () => {
    const payload = { detail: { code: 'task_manager_locked', reason: 'subtasks_and_blockers', detail: 'cannot be ticked: ...', blocking: {
      subtasks: [{ id: 2, title: 'write the test', state: 'open' }], blockers: [{ id: 7, kind: 'install', text: 'the 1.17 install' }] } } };
    expect(lockFromPayload(payload)).not.toBeNull();
    expect(explain(new ApiError('locked', 409, 'task_manager_locked', payload)))
      .toBe("locked: subtasks not done (1): 'write the test' (open); still waiting on the 1.17 install.");
    expect(lockFromPayload({ detail: { code: 'task_manager_invalid' } })).toBeNull();
  });
});
