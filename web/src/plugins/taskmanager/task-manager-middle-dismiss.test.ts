/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { isMiddleDismiss } from './task-manager-middle-dismiss';
import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';

const read = vi.hoisted(() => vi.fn());
vi.mock('./huddle.svelte', () => ({ readPost: read }));

const msg = (id: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, unread: kind !== 'question', created_at: id, seq: id, ...extra });
const item = (thread: unknown[]) => ({
  id: 1, list: 'all', text: 't', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null, revision: 1,
  created_seq: 1, seq: 1, deleted: false, unread: false, group: 7, status: 'question', section: 'question', thread,
});
const parts = { posts: 'block', questions: true, reply: false };

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await tick(); flushSync(); };
beforeEach(() => read.mockClear());
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

async function draw(component: unknown, props: Record<string, unknown>): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(component as never, { target: host, props });
  await settle();
  return host;
}
const press = (el: Element, type: 'auxclick' | 'mousedown', button = 1): MouseEvent => {
  const event = new MouseEvent(type, { button, bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  return event;
};

describe('the guard', () => {
  test('only the middle button on a plain spot counts', () => {
    const span = document.createElement('span');
    expect(isMiddleDismiss({ button: 1, target: span })).toBe(true);
    expect(isMiddleDismiss({ button: 0, target: span })).toBe(false);
    expect(isMiddleDismiss({ button: 2, target: span })).toBe(false);
    for (const tag of ['a', 'button', 'input', 'textarea', 'select']) expect(isMiddleDismiss({ button: 1, target: document.createElement(tag) }), tag).toBe(false);
  });
});

describe('an info or look post', () => {
  test('a middle click dismisses exactly that post through readPost, and the autoscroll press is cancelled', async () => {
    const it = item([msg(10, 'info', 'first info'), msg(11, 'attention', 'a look')]);
    const host = await draw(TaskManagerRowPosts, { item: it as never, parts: parts as never });
    const post = host.querySelector('[data-task-manager-post="10"]')!;
    expect(press(post, 'mousedown').defaultPrevented).toBe(true);
    press(post, 'auxclick');
    expect(read).toHaveBeenCalledTimes(1);
    expect(read.mock.calls[0]![1]).toMatchObject({ id: 10 });
    press(host.querySelector('[data-task-manager-post="11"]')!, 'auxclick');
    expect(read.mock.calls[1]![1]).toMatchObject({ id: 11 });
  });

  test('a link, the dismiss key and a left click fire nothing', async () => {
    const it = item([msg(10, 'info', 'an info [a link](https://example.com/x)')]);
    const host = await draw(TaskManagerRowPosts, { item: it as never, parts: parts as never });
    const link = host.querySelector('[data-task-manager-post="10"] a')!;
    expect(link).not.toBeNull();
    expect(press(link, 'mousedown').defaultPrevented).toBe(false);
    expect(press(link, 'auxclick').defaultPrevented).toBe(false);
    press(host.querySelector('[data-task-manager-post-read="10"]')!, 'auxclick');
    press(host.querySelector('[data-task-manager-post="10"]')!, 'auxclick', 0);
    expect(read).not.toHaveBeenCalled();
  });

  test('a question is never dismissed by a middle click', async () => {
    const it = item([msg(11, 'question', 'which one?')]);
    const host = await draw(TaskManagerRowPosts, { item: it as never, parts: parts as never });
    const question = host.querySelector('[data-task-manager-post="11"]')!;
    expect(question).not.toBeNull();
    expect(press(question, 'mousedown').defaultPrevented).toBe(false);
    press(question, 'auxclick');
    expect(read).not.toHaveBeenCalled();
  });

  test('a card with nothing to dismiss (a read info, a plain reply) draws no dismissable post and fires nothing', async () => {
    const it = item([msg(10, 'info', 'already read', { unread: false }), msg(12, 'reply', 'a plain reply', { author: 'joe' })]);
    const host = await draw(TaskManagerRowPosts, { item: it as never, parts: parts as never });
    for (const el of host.querySelectorAll('li, p, div')) press(el, 'auxclick');
    expect(read).not.toHaveBeenCalled();
  });
});
