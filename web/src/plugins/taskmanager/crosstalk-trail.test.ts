/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ paths: [] as string[], messages: [] as unknown[], fail: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      server.paths.push(path);
      if (server.fail) throw Object.assign(new Error('gone'), { status: 404 });
      return { task_item: 934, messages: server.messages };
    },
  };
});

import CrosstalkTrail from './CrosstalkTrail.svelte';
import { trailPath, trailWho } from './crosstalk-trail';
import type { HuddleItem } from './huddle-model';

const item = { id: 934, text: 'trace me', thread: [] } as unknown as HuddleItem;
const row = (id: string, from: string, to: string, preview: string) => ({
  id, thread: 't-1', sender_name: from, receiver_name: to, created_at: 1760000000, status: 'delivered', preview,
});

let app: ReturnType<typeof mount> | null = null;

async function show(): Promise<void> {
  app = mount(CrosstalkTrail, { target: document.body, props: { item } });
  await tick();
  await tick();
  flushSync();
}

afterEach(() => {
  if (app) void unmount(app);
  app = null;
  document.body.innerHTML = '';
  server.paths = [];
  server.messages = [];
  server.fail = false;
});

describe('crosstalk trail', () => {
  test('lists each message as from > to, time and first line, oldest first, from the item route', async () => {
    server.messages = [row('m-1', 'Alice', 'Bob', 'please review the diff'), row('m-2', 'Bob', 'Alice', 'looks good')];
    await show();
    expect(server.paths[0]).toBe(trailPath(934));
    const rows = [...document.querySelectorAll('[data-task-manager-trail-row]')];
    expect(rows.map((r) => r.querySelector('.hdt-trail-who')?.textContent)).toEqual(['Alice > Bob', 'Bob > Alice']);
    expect(rows[0]?.querySelector('.hdt-trail-line')?.textContent).toBe('please review the diff');
    expect(rows[0]?.querySelector('.hdt-trail-time')?.textContent).toMatch(/\d\d:\d\d/);
    expect(document.querySelector('.hdt-trail-label')?.textContent).toBe('crosstalk trail');
  });

  test('draws nothing for an item with no crosstalk, and nothing when the read fails', async () => {
    await show();
    expect(document.querySelector('[data-task-manager-trail]')).toBeNull();
    unmount(app!);
    document.body.innerHTML = '';
    server.fail = true;
    await show();
    expect(document.querySelector('[data-task-manager-trail]')).toBeNull();
  });

  test('a missing receiver reads as an unknown agent', () => {
    expect(trailWho(row('m-3', 'Alice', '', 'x') as never, 'unknown agent')).toBe('Alice > unknown agent');
  });
});
