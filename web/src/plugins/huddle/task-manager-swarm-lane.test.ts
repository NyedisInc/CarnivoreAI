import { afterEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => ({ reads: [] as string[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      server.reads.push(path);
      if (path.startsWith('/cplugs/huddle/aggregate?live_only=1')) return { cursor: 1, groups: [] };
      if (path.startsWith('/cplugs/huddle/lists/')) return { list: (path.split('/')[4] ?? '').split('?')[0], revision: 1, cursor: 1, groups: [], items: [] };
      return {};
    },
  };
});

import { holdSwarmLane, readQuery, selectList } from './huddle.svelte';
import { taskManagerPrefs } from './task-manager-prefs.svelte';

afterEach(() => {
  server.reads.length = 0;
  taskManagerPrefs.hideCompleted = false;
});

describe('the Task Manager view and the Swarm lane', () => {
  test('a Task Manager read never asks for Swarm-made items', async () => {
    await selectList('12');
    expect(server.reads.filter((p) => p.startsWith('/cplugs/huddle/lists/'))).toEqual(['/cplugs/huddle/lists/12?live_only=1']);
    expect(readQuery(null)).toBe('?live_only=1');
  });

  test('the Tasks Viewer reads its held list with both lanes, and only while it holds it', async () => {
    await selectList('12');
    server.reads.length = 0;
    const release = holdSwarmLane('12');
    await vi.waitFor(() => expect(server.reads).toContain('/cplugs/huddle/lists/12?live_only=1&include_swarm=1'));
    await selectList('18');
    expect(server.reads.filter((p) => p.startsWith('/cplugs/huddle/lists/'))).toEqual(['/cplugs/huddle/lists/12?live_only=1&include_swarm=1', '/cplugs/huddle/lists/18?live_only=1']);
    release();
    expect(readQuery('12')).toBe('?live_only=1');
  });

  test('hide completed and the Swarm lane share one query', () => {
    taskManagerPrefs.hideCompleted = true;
    const release = holdSwarmLane('agent:4');
    expect(readQuery('agent:4')).toBe('?live_only=1&hide_completed=1&include_swarm=1');
    expect(readQuery(null)).toBe('?live_only=1&hide_completed=1');
    release();
  });

  test('a stale release does not drop a newer hold', () => {
    const first = holdSwarmLane('12');
    const second = holdSwarmLane('13');
    first();
    expect(readQuery('13')).toBe('?live_only=1&include_swarm=1');
    second();
    expect(readQuery('13')).toBe('?live_only=1');
  });
});
