/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ patches: [] as Record<string, unknown>[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH') { server.patches.push(JSON.parse(String(init.body)) as Record<string, unknown>); return {}; }
      return {};
    },
  };
});
vi.mock('./huddle-send-many.svelte', () => ({ sendLists: async () => true }));

import { closeTickConfirm, tickConfirm, tickItem } from './task-manager-tick-confirm.svelte';
import TaskManagerTickConfirm from './TaskManagerTickConfirm.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; closeTickConfirm(); server.patches.length = 0; document.body.innerHTML = ''; });

async function mountDialog(): Promise<void> {
  app = mount(TaskManagerTickConfirm, { target: document.body });
  await tick();
}

describe('tick confirm', () => {
  test('a review tick approves with no dialog', async () => {
    await mountDialog();
    await tickItem(mk(1, { status: 'review' }) as never, true);
    flushSync();
    expect(tickConfirm.open).toBe(false);
    expect(document.querySelector('[data-task-manager-tick-confirm]')).toBeNull();
    expect(server.patches).toHaveLength(1);
  });

  test('an open tick shows the dialog; cancel approves nothing', async () => {
    await mountDialog();
    await tickItem(mk(2) as never, true);
    flushSync();
    expect(document.querySelector('[data-task-manager-tick-confirm="2"]')).not.toBeNull();
    expect(document.body.textContent).toContain('close this item?');
    expect(server.patches).toHaveLength(0);
    document.querySelector<HTMLElement>('[data-task-manager-tick-cancel]')!.click();
    flushSync();
    expect(document.querySelector('[data-task-manager-tick-confirm]')).toBeNull();
    expect(server.patches).toHaveLength(0);
  });

  test('Escape approves nothing', async () => {
    await mountDialog();
    await tickItem(mk(3, { status: 'working' }) as never, true);
    flushSync();
    document.querySelector('[data-task-manager-tick-confirm]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(tickConfirm.open).toBe(false);
    expect(server.patches).toHaveLength(0);
  });

  test('close and Enter approve', async () => {
    await mountDialog();
    await tickItem(mk(4) as never, true);
    flushSync();
    document.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')!.click();
    await tick(); await tick();
    expect(server.patches).toHaveLength(1);
    expect(server.patches[0]).toMatchObject({ approved: true });
    await tickItem(mk(5) as never, true);
    flushSync();
    document.querySelector('[data-task-manager-tick-confirm]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await tick(); await tick();
    expect(server.patches).toHaveLength(2);
  });

  test('an untick never asks', async () => {
    await mountDialog();
    await tickItem(mk(6, { state: 'done' }) as never, false);
    expect(tickConfirm.open).toBe(false);
    expect(server.patches[0]).toMatchObject({ approved: false });
  });

  const check = (id: number, checked: boolean) => ({ id: String(id), label: `check ${id}`, checked, checked_by: null, checked_at: null });

  test('a review tick with unchecked review checks warns, naming how many, and approves nothing', async () => {
    await mountDialog();
    const task = mk(7, { status: 'review', review_checks: [check(1, true), check(2, false), check(3, false)] });
    expect(await tickItem(task as never, true)).toBe(false);
    flushSync();
    expect(document.querySelector('[data-task-manager-confirm-mode="checks"]')).not.toBeNull();
    expect(document.querySelector('[data-task-manager-checks-ask]')!.textContent).toContain('2');
    expect(server.patches).toHaveLength(0);
    document.querySelector<HTMLElement>('[data-task-manager-tick-cancel]')!.click();
    flushSync();
    expect(document.querySelector('[data-task-manager-tick-confirm]')).toBeNull();
    expect(server.patches).toHaveLength(0);
  });

  test('confirming the warning approves', async () => {
    await mountDialog();
    await tickItem(mk(8, { status: 'review', review_checks: [check(1, false)] }) as never, true);
    flushSync();
    document.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')!.click();
    await tick(); await tick();
    expect(server.patches).toHaveLength(1);
    expect(server.patches[0]).toMatchObject({ approved: true });
  });

  test('a review tick with every check done, or no checks, goes straight through', async () => {
    await mountDialog();
    await tickItem(mk(9, { status: 'review', review_checks: [check(1, true)] }) as never, true);
    await tickItem(mk(10, { status: 'review', review_checks: [] }) as never, true);
    expect(tickConfirm.open).toBe(false);
    expect(server.patches).toHaveLength(2);
  });
});
