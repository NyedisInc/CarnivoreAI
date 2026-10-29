/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { createCloseCue } from './task-manager-close-cue.svelte';
import { isDismissTarget } from './task-manager-posts';
import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';

const msg = (id: number, kind: string, text: string) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, unread: kind !== 'question', created_at: id, seq: id });
const item = {
  id: 1, list: 'all', text: 't', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null, revision: 1,
  created_seq: 1, seq: 1, deleted: false, unread: false, group: 7, status: 'question', section: 'question',
  thread: [msg(10, 'info', 'an info [a link](https://example.com/x)'), msg(11, 'question', 'which one?')],
};
const parts = { posts: 'block', questions: true, reply: false };

const read = vi.hoisted(() => vi.fn());
vi.mock('./huddle.svelte', () => ({ readPost: read }));

function rule(selector: string): string {
  const css = (readFileSync(join(process.cwd(), 'src/cplugs/huddle/TaskManagerRowPosts.svelte'), 'utf8').split('<style>')[1] ?? '').replace('@layer components {', '');
  const found = [...css.matchAll(/(^|\n)\s*([^{}\n]+)\{([^}]*)\}/g)].filter((m) => (m[2] as string).trim() === selector);
  return (found[found.length - 1]?.[3] as string | undefined) ?? '';
}

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await tick(); flushSync(); };
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

async function mountPosts(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerRowPosts, { target: host, props: { item: item as never, parts: parts as never } });
  await settle();
  return host;
}
const move = (el: Element, shiftKey: boolean) => el.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, shiftKey }));
const key = (type: string, shiftKey: boolean) => window.dispatchEvent(new KeyboardEvent(type, { shiftKey }));
const layer = (host: HTMLElement) => host.querySelector('[data-task-manager-post-close]');

describe('close cue', () => {
  test('pure: a plain spot dismisses, a link or button does not', () => {
    expect(isDismissTarget(document.createElement('span'))).toBe(true);
    expect(isDismissTarget(document.createElement('a'))).toBe(false);
    expect(isDismissTarget(null)).toBe(true);
  });

  test('pure: controller needs shift and a dismissable spot together, and clear resets', () => {
    const cue = createCloseCue();
    cue.point(5, { shiftKey: false, target: document.createElement('span') });
    expect(cue.active).toBeNull();
    cue.key({ shiftKey: true });
    expect(cue.active).toBe(5);
    cue.leave(5);
    expect(cue.active).toBeNull();
  });

  test('shows on shift plus hover, follows keyup and blur', async () => {
    const host = await mountPosts();
    const text = host.querySelector('[data-task-manager-post="10"] .tkm-post-text')!;
    move(text, false);
    key('keydown', true);
    await settle();
    expect(layer(host)?.textContent).toBe('close');
    expect(layer(host)?.closest('[data-task-manager-post="10"]')).not.toBeNull();
    key('keyup', false);
    await settle();
    expect(layer(host)).toBeNull();
    key('keydown', true);
    await settle();
    expect(layer(host)).not.toBeNull();
    window.dispatchEvent(new Event('blur'));
    await settle();
    expect(layer(host)).toBeNull();
  });

  test('no layer over a link inside the post', async () => {
    const host = await mountPosts();
    const link = host.querySelector('[data-task-manager-post="10"] a')!;
    expect(link).not.toBeNull();
    move(link, true);
    key('keydown', true);
    await settle();
    expect(layer(host)).toBeNull();
  });

  test('no layer on a question', async () => {
    const host = await mountPosts();
    move(host.querySelector('[data-task-manager-post="11"]')!, true);
    key('keydown', true);
    await settle();
    expect(layer(host)).toBeNull();
  });
});

describe('click folds and opens', () => {
  const LONG = 'x'.repeat(300);
  const long = { ...item, thread: [msg(10, 'info', LONG), msg(11, 'question', LONG)] };

  async function mountLong(): Promise<HTMLElement> {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerRowPosts, { target: host, props: { item: long as never, parts: parts as never } });
    await settle();
    return host;
  }
  const click = (el: Element, shiftKey = false) => el.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey }));

  test('a plain click on the folded text opens, a click again folds back', async () => {
    const host = await mountLong();
    const post = host.querySelector('[data-task-manager-post="10"]')!;
    expect(post.getAttribute('data-task-manager-post-folded')).toBe('true');
    click(post.querySelector('.tkm-post-text')!);
    await settle();
    expect(post.getAttribute('data-task-manager-post-folded')).toBe('false');
    click(post.querySelector('.tkm-post-text')!);
    await settle();
    expect(post.getAttribute('data-task-manager-post-folded')).toBe('true');
  });

  test('a question opens the same way', async () => {
    const host = await mountLong();
    click(host.querySelector('[data-task-manager-post="11"]')!);
    await settle();
    expect(host.querySelector('[data-task-manager-post="11"]')!.getAttribute('data-task-manager-post-folded')).toBe('false');
  });

  test('shift-click still dismisses and does not open', async () => {
    const host = await mountLong();
    click(host.querySelector('[data-task-manager-post="10"] .tkm-post-text')!, true);
    await settle();
    expect(read).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[data-task-manager-post="10"]')!.getAttribute('data-task-manager-post-folded')).toBe('true');
  });

  test('the chevron toggles once (not twice through the line)', async () => {
    const host = await mountLong();
    click(host.querySelector('[data-task-manager-post-fold="10"]')!);
    await settle();
    expect(host.querySelector('[data-task-manager-post="10"]')!.getAttribute('data-task-manager-post-folded')).toBe('false');
  });
});

describe('a foldable post is one click target, opened or folded (Joe, 2026-10-05)', () => {
  const LONG = 'x'.repeat(300);
  const long = { ...item, thread: [msg(10, 'info', LONG + ' [a link](https://example.com/y)'), msg(12, 'info', 'short one'), msg(11, 'question', LONG)] };
  const click = (el: Element, shiftKey = false) => el.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey }));

  async function mountLong(): Promise<HTMLElement> {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerRowPosts, { target: host, props: { item: long as never, parts: parts as never } });
    await settle();
    return host;
  }
  const folded = (host: HTMLElement, id: number) => host.querySelector(`[data-task-manager-post="${id}"]`)!.getAttribute('data-task-manager-post-folded');

  test('a click anywhere toggles it in both states, a question included', async () => {
    const host = await mountLong();
    for (const id of [10, 11]) {
      const post = host.querySelector(`[data-task-manager-post="${id}"]`)!;
      expect(folded(host, id)).toBe('true');
      click(post);
      await settle();
      expect(folded(host, id)).toBe('false');
      click(post.querySelector('.tkm-post-text')!);
      await settle();
      expect(folded(host, id)).toBe('true');
    }
  });

  test('a link click and a text selection do not toggle', async () => {
    const host = await mountLong();
    const post = host.querySelector('[data-task-manager-post="10"]')!;
    click(post);
    await settle();
    expect(folded(host, 10)).toBe('false');
    click(post.querySelector('a')!);
    await settle();
    expect(folded(host, 10)).toBe('false');
    const selection = vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'some words' } as Selection);
    click(post.querySelector('.tkm-post-text')!);
    await settle();
    expect(folded(host, 10)).toBe('false');
    selection.mockRestore();
    click(post.querySelector('.tkm-post-text')!);
    await settle();
    expect(folded(host, 10)).toBe('true');
  });

  test('cursor: pointer on every foldable post, none on a short one', async () => {
    const host = await mountLong();
    expect(rule('.tkm-posts > :global(.tkm-posts-post[data-task-manager-post-folded])')).toContain('cursor: pointer');
    expect(host.querySelector('[data-task-manager-post="12"]')!.hasAttribute('data-task-manager-post-folded')).toBe(false);
    click(host.querySelector('[data-task-manager-post="12"]')!);
    await settle();
    expect(host.querySelector('[data-task-manager-post="12"]')!.hasAttribute('data-task-manager-post-folded')).toBe(false);
  });

  test('the remove cursor shows with Shift over an info and a look, never a question, and goes with Shift', async () => {
    const host = await mountLong();
    expect(rule('.tkm-posts > :global(.tkm-posts-post.tkm-posts-post--closing[data-task-manager-post])')).toMatch(/cursor:\s*url\("data:image\/svg\+xml[^)]*\) 12 12, not-allowed/);
    const info = host.querySelector('[data-task-manager-post="10"]')!;
    move(info.querySelector('.tkm-post-text')!, false);
    expect(info.classList.contains('tkm-posts-post--closing')).toBe(false);
    key('keydown', true);
    await settle();
    expect(info.classList.contains('tkm-posts-post--closing')).toBe(true);
    key('keyup', false);
    await settle();
    expect(info.classList.contains('tkm-posts-post--closing')).toBe(false);
    move(host.querySelector('[data-task-manager-post="11"]')!, true);
    key('keydown', true);
    await settle();
    expect(host.querySelector('[data-task-manager-post="11"]')!.classList.contains('tkm-posts-post--closing')).toBe(false);
  });
});
