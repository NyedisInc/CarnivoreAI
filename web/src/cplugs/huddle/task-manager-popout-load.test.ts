/** @vitest-environment jsdom */
import { afterAll, describe, expect, test, vi } from 'vitest';

const rig = vi.hoisted(() => {
  const handlers = new Set<(frame: { type?: string }) => void>();
  let hello: Record<string, unknown> | null = null;
  (globalThis as Record<string, unknown>).AppEvents = {
    subscribe(handler: (frame: { type?: string }) => void) {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
    isConnected: () => hello !== null,
    lastHello: () => hello,
  };
  return {
    calls: [] as string[],
    settings: { hideCompleted: true, view: 'area' } as Record<string, unknown>,
    revision: 1,
    emit(frame: Record<string, unknown>) {
      if (frame.type === 'events.hello') hello = frame;
      for (const handler of [...handlers]) handler(frame);
    },
  };
});

const MARKER = { delta_seq: 0, delta_epoch: 'e1' };
const later = <T>(ms: number, value: T): Promise<T> => new Promise((resolve) => setTimeout(() => resolve(value), ms));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path);
      if (path === '/cplugs/huddle') return later(60, { revision: rig.revision, settings: { ...rig.settings } });
      if (path === '/cplugs/huddle/lists') return later(40, { cursor: 1, lists: [], ...MARKER });
      if (path.startsWith('/cplugs/huddle/aggregate')) return later(40, { cursor: 1, groups: [], ...MARKER });
      return {};
    },
  };
});

import { huddle, startTaskManager } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));
const reads = (prefix: string): string[] => rig.calls.filter((p) => p.split('?')[0] === prefix);

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager pop-out load', () => {
  test('a pop-out load costs one /lists and one /aggregate, read with the stored hide completed', async () => {
    startTaskManager(AGGREGATE);
    await wait(10);
    rig.emit({ type: 'events.hello', resource_topics: ['cplug.huddle.list', 'cplug.huddle.delta', 'cplugs'] });
    await wait(800);
    const lists = reads('/cplugs/huddle/lists').length;
    const aggregate = reads('/cplugs/huddle/aggregate');
    console.info(`pop-out load: ${lists} /lists, ${aggregate.length} /aggregate (before: 2 plus 2)`);
    expect(huddle.groups).toEqual([]);
    expect(lists).toBe(1);
    expect(aggregate).toHaveLength(1);
    expect(aggregate[0]).toContain('hide_completed=1');

    rig.calls.length = 0;
    rig.settings = { hideCompleted: false, view: 'area' };
    rig.revision = 2;
    rig.emit({ type: 'resources.changed', topics: ['cplugs'], seq: 1 });
    await wait(600);
    const again = reads('/cplugs/huddle/aggregate');
    expect(again).toHaveLength(1);
    expect(again[0]).not.toContain('hide_completed=1');
  });
});
