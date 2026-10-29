/** @vitest-environment jsdom */
import { afterAll, describe, expect, test, vi } from 'vitest';

const rig = vi.hoisted(() => {
  const handlers = new Set<(frame: { type?: string }) => void>();
  let hello: Record<string, unknown> | null = null;
  const events = {
    subscribe(handler: (frame: { type?: string }) => void) {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
    isConnected: () => hello !== null,
    lastHello: () => hello,
  };
  (globalThis as Record<string, unknown>).AppEvents = events;
  return {
    calls: [] as string[],
    emit(frame: Record<string, unknown>) {
      if (frame.type === 'events.hello') hello = frame;
      for (const handler of [...handlers]) handler(frame);
    },
  };
});

const item = (id: number, state = 'open', text = `item ${id}`) => ({
  id, list: 'all', text, note: '', position: id, created_by: 'joe', state, kind: 'task', lane: 'task_manager',
  revision: 1, created_seq: id, seq: id, deleted: false, number: state === 'done' ? null : id, thread: [], thread_count: 0, thread_slim: true,
});
const LIVE = [1, 2, 3, 4, 5];
const DONE = 569;
const MARKER = { delta_seq: 0, delta_epoch: 'e1' };

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path.split('?')[0] ?? path);
      if (path === '/cplugs/huddle/lists') return { cursor: 5, lists: [{ key: 'all', name: null, project_id: null, items: 5, open: 5, review: 0, questions: 0, claude_seq: 0 }], ...MARKER };
      if (path.startsWith('/cplugs/huddle/aggregate')) {
        return { cursor: 5, groups: [{ list: 'all', name: null, project_id: null, revision: 5, groups: [], done_count: DONE, items: LIVE.map((id) => item(id)) }], ...MARKER };
      }
      if (path.startsWith('/cplugs/huddle/lists/all/done')) return { list: 'all', total: DONE + 1, next_offset: 50, items: [item(3, 'done'), item(100, 'done')] };
      return {};
    },
  };
});

import { doneCount, huddle, startTaskManager } from './huddle.svelte';
import { holdDone } from './task-manager-done.svelte';

const FULL = ['/cplugs/huddle/lists', '/cplugs/huddle/aggregate'];
const fullReads = (): number => rig.calls.filter((path) => FULL.includes(path)).length;
const doneReads = (): number => rig.calls.filter((path) => path === '/cplugs/huddle/lists/all/done').length;
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 320));
const frame = (seq: number, live: number[], items: unknown[], deleted: number[], done: number): Record<string, unknown> => ({
  type: 'cplug.data', topic: 'cplug.huddle.delta',
  data: {
    seq, epoch: 'e1',
    lists: [{ list: 'all', revision: 5 + seq, groups: [], inbox: null, order: live, numbers: Object.fromEntries(live.map((id) => [String(id), id])),
      swarm: [], done_count: done, done_swarm: 0, items, deleted }],
  },
});

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager item delta on a live-only window', () => {
  test('changes on a list with done items cost zero full reads; the done count follows', async () => {
    startTaskManager();
    rig.emit({ type: 'events.hello', resource_topics: ['cplug.huddle.list', 'cplug.huddle.delta'] });
    await settle();
    expect(huddle.groups?.[0]?.items.map((i) => i.id)).toEqual(LIVE);
    expect(doneCount('all')).toBe(DONE);

    rig.calls.length = 0;
    rig.emit(frame(1, LIVE, [item(2, 'open', 'edited')], [], DONE));
    await settle();
    expect(huddle.groups?.[0]?.items.find((i) => i.id === 2)?.text).toBe('edited');

    rig.emit(frame(2, [1, 2, 4, 5], [item(3, 'done')], [3], DONE + 1));
    await settle();
    expect(huddle.groups?.[0]?.items.map((i) => i.id)).toEqual([1, 2, 4, 5]);
    expect(doneCount('all')).toBe(DONE + 1);
    const closed = fullReads();
    expect(closed).toBe(0);

    const release = holdDone('all');
    await settle();
    rig.calls.length = 0;
    rig.emit(frame(3, [1, 2, 4, 5], [item(1, 'open', 'edited too')], [], DONE + 1));
    await settle();
    expect(fullReads()).toBe(0);
    expect(doneReads()).toBe(1);
    expect(huddle.groups?.[0]?.items.map((i) => i.id)).toEqual([1, 2, 4, 5, 3, 100]);
    release();
    console.info(`full reads per change on a list with ${DONE} done items: ${closed} (before: one /lists plus one /aggregate per change)`);
  });
});
