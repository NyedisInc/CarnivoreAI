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

const item = (id: number, text = `item ${id}`) => ({
  id, list: 'all', text, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task', lane: 'task_manager',
  revision: 1, created_seq: id, seq: id, deleted: false, number: id, thread: [], thread_count: 0, thread_slim: true,
});
const ITEMS = [1, 2, 3, 4, 5].map((id) => item(id));
const MARKER = { delta_seq: 0, delta_epoch: 'e1' };

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path.split('?')[0] ?? path);
      if (path === '/cplugs/huddle/lists') return { cursor: 5, lists: [{ key: 'all', name: null, project_id: null, items: 5, open: 5, review: 0, questions: 0, claude_seq: 0 }], ...MARKER };
      if (path.startsWith('/cplugs/huddle/aggregate')) {
        return { cursor: 5, groups: [{ list: 'all', name: null, project_id: null, revision: 5, groups: [], items: structuredClone(ITEMS) }], ...MARKER };
      }
      return {};
    },
  };
});

import { huddle, startTaskManager } from './huddle.svelte';
import type { HuddleItem } from './huddle-model';

const READS = ['/cplugs/huddle/lists', '/cplugs/huddle/aggregate'];
const listReads = (): number => rig.calls.filter((path) => READS.includes(path)).length;
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 320));
const changed = (): void => rig.emit({ type: 'resources.changed', topics: ['cplug.huddle.list:all'], seq: 1 });
const delta = (seq: number, text: string): Record<string, unknown> => ({
  type: 'cplug.data', topic: 'cplug.huddle.delta',
  data: {
    seq, epoch: 'e1',
    lists: [{ list: 'all', revision: 5 + seq, groups: [], inbox: null, order: [1, 2, 3, 4, 5], numbers: { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5 },
      swarm: [], items: [item(3, text)], deleted: [] }],
  },
});

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager item delta', () => {
  test('one edit is patched in place with no list read; a gap costs one full read', async () => {
    startTaskManager();
    rig.emit({ type: 'events.hello', resource_topics: ['cplug.huddle.list'] });
    await settle();
    expect(huddle.groups?.[0]?.items).toHaveLength(5);

    rig.calls.length = 0;
    changed();
    await settle();
    const before = listReads();
    expect(before).toBe(2);

    rig.emit({ type: 'events.hello', resource_topics: ['cplug.huddle.list', 'cplug.huddle.delta'] });
    await settle();
    const shared = (): HuddleItem[] => huddle.groups?.[0]?.items ?? [];
    const untouched = shared()[0];

    rig.calls.length = 0;
    changed();
    rig.emit(delta(1, 'edited once'));
    await settle();
    const after = listReads();
    expect(after).toBe(0);
    expect(shared().find((i) => i.id === 3)?.text).toBe('edited once');
    expect(shared()[0]).toBe(untouched);
    expect(huddle.groups?.[0]?.revision).toBe(6);

    rig.calls.length = 0;
    rig.emit(delta(3, 'after a gap'));
    await settle();
    expect(rig.calls.filter((path) => path === '/cplugs/huddle/aggregate')).toHaveLength(1);
    expect(rig.calls.filter((path) => path === '/cplugs/huddle/lists')).toHaveLength(1);
    console.info(`list reads per window per change: before ${before}, after ${after}; a gap: one full read`);
  });
});
