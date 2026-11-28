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
    name: null as string | null,
    emit(frame: Record<string, unknown>) {
      if (frame.type === 'events.hello') hello = frame;
      for (const handler of [...handlers]) handler(frame);
    },
  };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path.split('?')[0] ?? path);
      const MARKER = { delta_seq: 0, delta_epoch: 'e1' };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 1, ...MARKER, lists: [{ key: '102', name: rig.name, project_id: 102, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0 }] };
      }
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 1, groups: [], ...MARKER };
      return {};
    },
  };
});

import { huddle, startTaskManager } from './huddle.svelte';

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 320));

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager list names follow project writes', () => {
  test('a projects push re-reads the lists, so the tab gets the new name', async () => {
    startTaskManager();
    rig.emit({ type: 'events.hello', resource_topics: ['cplug.taskmanager.list', 'cplug.taskmanager.delta', 'projects'] });
    await settle();
    expect(huddle.lists.find((l) => l.key === '102')?.name ?? null).toBeNull();

    rig.name = 'Fleet Console';
    rig.emit({ type: 'resources.changed', topics: ['projects'], seq: 1 });
    await settle();
    expect(huddle.lists.find((l) => l.key === '102')?.name).toBe('Fleet Console');
  });
});
