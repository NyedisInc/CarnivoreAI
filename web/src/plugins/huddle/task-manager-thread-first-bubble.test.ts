/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import HuddleThread from './HuddleThread.svelte';

vi.mock('./huddle.svelte', () => ({ readPost: vi.fn(), reply: vi.fn() }));

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

const msg = (id: number, author: string, kind: string, text: string) =>
  ({ id, item_id: 1, author, kind, text, answered: false, unread: false, created_at: id, seq: id });

async function draw(item: Record<string, unknown>): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleThread as never, { target: host, props: { item, firstBubble: true } });
  flushSync();
  await tick();
  await tick();
  return host;
}

describe('the item text is the first bubble', () => {
  test('a claude-created item: first bubble on claude\'s side with the text', async () => {
    const host = await draw({ id: 1, list: 'all', text: 'the original', created_by: 'claude', state: 'open', thread: [msg(1, 'joe', 'reply', 'ok')] });
    const first = host.querySelector<HTMLElement>('[data-task-manager-first="1"]')!;
    expect(first.textContent).toContain('the original');
    expect(first.classList.contains('hdt-msg--claude')).toBe(true);
    expect(first.dataset.by).toBe('claude');
    const items = [...host.querySelectorAll('.hdt-list > li')];
    expect(items[0]).toBe(first);
  });

  test('an owner-created item: first bubble on the owner\'s side', async () => {
    const host = await draw({ id: 1, list: 'all', text: 'mine', created_by: 'joe', state: 'open', thread: [] });
    const first = host.querySelector<HTMLElement>('[data-task-manager-first="1"]')!;
    expect(first.classList.contains('hdt-msg--joe')).toBe(true);
    expect(first.dataset.hb).toBe('owner');
  });
});

describe('one scroll box, reply outside it', () => {
  test('the bubbles are in the single box; the reply box is a sibling, not inside', async () => {
    const host = await draw({ id: 1, list: 'all', text: 't', created_by: 'claude', state: 'open', thread: [msg(1, 'claude', 'info', 'a'), msg(2, 'joe', 'reply', 'b')] });
    const boxes = host.querySelectorAll('[data-task-manager-thread-box]');
    expect(boxes.length).toBe(1);
    const box = boxes[0]!;
    expect(box.querySelectorAll('[data-hb]').length).toBe(3);
    const reply = host.querySelector('.hdt-reply')!;
    expect(reply).not.toBeNull();
    expect(box.contains(reply)).toBe(false);
  });

  test('opens scrolled to the bottom', async () => {
    const tops: number[] = [];
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    Object.defineProperty(proto, 'scrollHeight', { configurable: true, get() { return 777; } });
    Object.defineProperty(proto, 'scrollTop', { configurable: true, get() { return 0; }, set(v: number) { if (this.dataset.taskManagerThreadBox) tops.push(v); } });
    try {
      await draw({ id: 1, list: 'all', text: 't', created_by: 'claude', state: 'open', thread: [msg(1, 'claude', 'info', 'a')] });
      expect(tops.at(-1)).toBe(777);
    } finally {
      delete proto.scrollTop;
      delete proto.scrollHeight;
    }
  });
});
