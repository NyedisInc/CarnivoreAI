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

const MARKER = { delta_seq: 0, delta_epoch: 'e1' };

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path.split('?')[0] ?? path);
      if (path === '/cplugs/huddle/lists') return { cursor: 1, lists: [], ...MARKER };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 1, groups: [], ...MARKER };
      return {};
    },
  };
});

import { holdAggregate, huddle, startTaskManager } from './huddle.svelte';

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));
const count = (path: string): number => rig.calls.filter((p) => p === path).length;

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager read queue', () => {
  test('a page load with many holders costs one /lists and one /aggregate', async () => {
    const releases = [holdAggregate(), holdAggregate()];
    startTaskManager();
    for (let n = 0; n < 6; n += 1) releases.push(holdAggregate());
    await wait(50);
    releases.push(holdAggregate(), holdAggregate(), holdAggregate());
    await wait(50);
    rig.emit({ type: 'events.hello', resource_topics: ['cplug.huddle.list', 'cplug.huddle.delta'] });
    await wait(600);
    const lists = count('/cplugs/huddle/lists');
    const aggregate = count('/cplugs/huddle/aggregate');
    console.info(`page load with ${releases.length} holders: ${lists} /lists, ${aggregate} /aggregate (before: 2 /lists plus 8 to 11 /aggregate)`);
    expect(huddle.groups).toEqual([]);
    expect(lists).toBe(1);
    expect(aggregate).toBe(1);

    rig.calls.length = 0;
    releases.push(holdAggregate());
    await wait(300);
    expect(rig.calls).toEqual([]);

    rig.emit({ type: 'events.closed' });
    await wait(300);
    rig.calls.length = 0;
    releases.push(holdAggregate(), holdAggregate(), holdAggregate());
    await wait(0);
    expect(rig.calls).toEqual(['/cplugs/huddle/aggregate']);
    await wait(300);
    expect(rig.calls).toEqual(['/cplugs/huddle/aggregate']);
    releases.forEach((release) => release());
  });
});
