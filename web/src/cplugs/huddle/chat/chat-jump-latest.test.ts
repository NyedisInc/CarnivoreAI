/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ entries: [] as unknown[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/agents/7') return { id: 7, display_name: 'Loki', rank: 'feature', state: 'awake', thread_key: '12', session_id: null, tmux_session: null };
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import ChatWidget from './ChatWidget.svelte';
import { chatSlotId } from './chat-model';
import { createChatStore } from './chat-store.svelte';

let app: object | null = null;
const post = (n: number) => ({ kind: 'agent', id: `msg:${n}`, at: 1, text: `line ${n}` });

function measure(el: HTMLElement, box: { height: number; top: number }): void {
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => 200 });
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => box.height });
  Object.defineProperty(el, 'scrollTop', { configurable: true, get: () => box.top, set: (v: number) => (box.top = Math.min(v, box.height - 200)) });
  el.scrollTo = ((opts: ScrollToOptions) => { box.top = Math.min(opts.top ?? 0, box.height - 200); }) as typeof el.scrollTo;
}

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

describe('the chat never scrolls under a reader who scrolled up (card 1496)', () => {
  test('scrolled up: a new message leaves scrollTop alone and counts on the jump key; at the bottom it follows', async () => {
    server.entries = [post(1), post(2), post(3)];
    const chat = createChatStore(7);
    document.body.innerHTML = '<div id="host"></div>';
    app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7), chat } });
    await chat.refresh();
    await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
    const scroller = document.querySelector<HTMLElement>('.hdc-scroll') as HTMLElement;
    const box = { height: 1000, top: 800 };
    measure(scroller, box);
    const key = (): HTMLButtonElement | null => document.querySelector<HTMLButtonElement>('[data-chat-latest]');
    expect(key()).toBeNull();

    box.top = 100;
    scroller.dispatchEvent(new Event('scroll'));
    flushSync();
    expect(key()).not.toBeNull();

    server.entries = [post(1), post(2), post(3), post(4), post(5)];
    box.height = 1200;
    await chat.refresh();
    await tick();
    await tick();
    expect(box.top).toBe(100);
    expect(key()?.dataset.chatLatestCount).toBe('2');
    expect(key()?.getAttribute('aria-label')).toBe('2 new, jump to the latest message');

    key()?.click();
    expect(box.top).toBe(1000);
    scroller.dispatchEvent(new Event('scroll'));
    flushSync();
    expect(key()).toBeNull();

    server.entries = [...server.entries, post(6)];
    box.height = 1400;
    await chat.refresh();
    await tick();
    await tick();
    expect(box.top).toBe(1200);
    expect(key()).toBeNull();
  });
});
