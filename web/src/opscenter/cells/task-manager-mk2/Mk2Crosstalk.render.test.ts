/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ messages: [] as unknown[] }));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return { ...real, authFetch: async () => ({ task_item: 7, messages: server.messages }) };
});

import Mk2Crosstalk from './Mk2Crosstalk.svelte';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

const item = { id: 7, text: 'trace me', thread: [] } as unknown as HuddleItem;
const row = (id: string, preview: string) => ({ id, thread: 't', sender_name: 'Alice', receiver_name: 'Bob', created_at: 1760000000, status: 'delivered', preview });
let app: ReturnType<typeof mount> | null = null;

async function show(): Promise<void> {
  app = mount(Mk2Crosstalk, { target: document.body, props: { item } });
  await tick(); await tick(); flushSync();
}

afterEach(() => { if (app) void unmount(app); app = null; document.body.innerHTML = ''; server.messages = []; });

describe('Mk2Crosstalk', () => {
  test('cards are closed by default and a click opens and closes one', async () => {
    server.messages = [row('m-1', 'please review the diff'), row('m-2', 'looks good')];
    await show();
    const cards = [...document.querySelectorAll<HTMLElement>('[data-mk2-crosstalk-card]')];
    expect(cards.map((c) => c.dataset.open)).toEqual(['false', 'false']);
    expect(cards[0]?.querySelector('.mk2-xt-who')?.textContent).toBe('Alice > Bob');
    cards[0]?.querySelector<HTMLButtonElement>('.mk2-xt-head')?.click(); flushSync();
    expect(cards[0]?.dataset.open).toBe('true');
    expect(cards[1]?.dataset.open).toBe('false');
    cards[0]?.querySelector<HTMLButtonElement>('.mk2-xt-head')?.click(); flushSync();
    expect(cards[0]?.dataset.open).toBe('false');
  });

  test('draws nothing without crosstalk', async () => {
    await show();
    expect(document.querySelector('[data-mk2-crosstalk]')).toBeNull();
  });
});
