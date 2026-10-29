/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ patches: [] as Record<string, unknown>[], stale: 0, accept: 9 }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH' && path === '/cplugs/huddle/items/5') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        server.patches.push(body);
        if (server.stale > 0 && body.expected_revision !== server.accept) {
          server.stale -= 1;
          throw new real.ApiError('stale', 409, 'task_manager_stale', { detail: { code: 'task_manager_stale', current: { revision: 9 } } });
        }
      }
      return {};
    },
  };
});

import ChatCard from './ChatCard.svelte';
import type { HuddleItem } from '../huddle-model';

let app: object | null = null;

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  server.patches.length = 0;
  server.accept = 9;
});

const item = { id: 5, list: 'agent:7', text: 'done', title: 'finished', note: '', position: 1, created_by: 'claude', state: 'open', kind: '',
               revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'review', thread: [] } as unknown as HuddleItem;

async function approveWithText(text: string): Promise<void> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatCard, { target: document.getElementById('host') as HTMLElement, props: { item: { ...item }, card: 'done', agentName: 'Loki' } });
  flushSync();
  const buttons = (): HTMLButtonElement[] => [...document.querySelectorAll<HTMLButtonElement>('.hdc-card button')];
  buttons().find((b) => b.className.includes('oc-btn') && !b.className.includes('confirm'))!.click();
  flushSync();
  const box = document.querySelector('.hdc-card-note') as HTMLTextAreaElement;
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  (document.querySelector('.hdc-card-note ~ * .oc-btn--confirm, .oc-btn--confirm:not([disabled])') as HTMLButtonElement).click();
  await vi.waitFor(() => expect(server.patches.length).toBeGreaterThan(0));
  for (let i = 0; i < 10; i += 1) await tick();
}

describe('approve with a note', () => {
  test('is one PATCH carrying the note, the tick and the revision', async () => {
    server.stale = 0;
    await approveWithText('looks right');
    expect(server.patches).toEqual([{ note: 'looks right', approved: true, expected_revision: 1 }]);
  });

  test('a 409 adopts the server revision and replays the same write once', async () => {
    server.stale = 1;
    await approveWithText('looks right');
    await vi.waitFor(() => expect(server.patches.length).toBe(2));
    expect(server.patches).toEqual([
      { note: 'looks right', approved: true, expected_revision: 1 },
      { note: 'looks right', approved: true, expected_revision: 9 },
    ]);
  });

  test('a second 409 is not replayed again', async () => {
    server.stale = 5;
    server.accept = 99;
    await approveWithText('x');
    await vi.waitFor(() => expect(server.patches.length).toBeGreaterThanOrEqual(2));
    for (let i = 0; i < 10; i += 1) await tick();
    expect(server.patches.length).toBe(2);
  });
});
