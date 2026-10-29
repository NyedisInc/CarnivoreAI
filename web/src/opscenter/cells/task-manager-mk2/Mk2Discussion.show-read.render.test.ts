/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const net = vi.hoisted(() => ({ calls: [] as string[] }));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      net.calls.push(path);
      return { id: 4, thread: [] };
    },
  };
});

import Mk2Discussion from './Mk2Discussion.svelte';
import type { Inspection, Message, Task } from '../../../cplugs/huddle/task-manager-design/model';

const message = (id: number): Message => ({ id: String(id), by: 'agent', time: 'now', text: `m${id}`, read: false });
const view = (): Inspection => ({ tab: 'discussion', earlier: false, approved: false, scroll: 0, boundary: 0 });
const task = (hiddenCount: number): Task => ({ id: 4, title: 't', project: 'p', state: 'open', agent: 'claude', text: 'x', messages: [message(3), message(4)], hiddenCount });
let app: ReturnType<typeof mount> | null = null;

async function show(t: Task, v: Inspection): Promise<void> {
  app = mount(Mk2Discussion, { target: document.body, props: { task: t, view: v, onResource: () => {} } });
  await tick(); flushSync();
}

afterEach(() => { if (app) void unmount(app); app = null; document.body.innerHTML = ''; net.calls.length = 0; });

describe('Mk2Discussion show read on a slim thread', () => {
  test('the toggle shows with the hidden count, and a click reads the whole thread then expands', async () => {
    const v = view();
    await show(task(5), v);
    const toggle = document.querySelector<HTMLButtonElement>('[data-task-manager-earlier]');
    expect(toggle).not.toBeNull();
    expect(toggle?.textContent).toContain('5');
    toggle?.click();
    await tick(); await tick(); flushSync();
    expect(net.calls).toEqual(['/cplugs/huddle/items/4']);
    expect(v.earlier).toBe(true);
  });

  test('no toggle when nothing is hidden', async () => {
    await show(task(0), view());
    expect(document.querySelector('[data-task-manager-earlier]')).toBeNull();
  });
});
