/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { KIND_COLORS } from './task-manager-posts';
import { threadTone } from './task-manager-bubbles';
import HuddleReview from './HuddleReview.svelte';
import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';
import HuddleThread from './HuddleThread.svelte';

vi.mock('./huddle.svelte', () => ({ readPost: vi.fn(), reply: vi.fn() }));

function rule(file: string, selector: string): string {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8');
  const css = (file.endsWith('.css') ? source : (source.split('<style>')[1] ?? '')).replace('@layer components {', '');
  const found = [...css.matchAll(/(^|\n)\s*([^{}\n]+)\{([^}]*)\}/g)].filter((m) => (m[2] as string).trim() === selector);
  return (found[found.length - 1]?.[3] as string | undefined) ?? '';
}

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await tick(); flushSync(); };
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

async function draw(component: never, props: Record<string, unknown>): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(component, { target: host, props });
  await settle();
  return host;
}

const msg = (id: number, author: string, kind: string, text: string) =>
  ({ id, item_id: 1, author, kind, text, answered: false, unread: false, created_at: id, seq: id });

describe('the review card', () => {
  test('the kind color is its own, used by no other post kind', () => {
    const others = [KIND_COLORS.question.color, KIND_COLORS.info.color, KIND_COLORS.look.color];
    expect(KIND_COLORS.review.color).toMatch(/^var\(--oc-/);
    expect(others).not.toContain(KIND_COLORS.review.color);
  });

  test('a bubble in that color; the location is in the review part with a small label', async () => {
    const host = await draw(HuddleReview as never, { id: 5, block: { action: 'tick', summary: '', hasMore: false, description: 'check the block', where: 'huddle tab > row', link: '' } });
    const card = host.querySelector<HTMLElement>('[data-task-manager-review="5"]')!;
    expect(card.style.getPropertyValue('--_post')).toBe(KIND_COLORS.review.color);
    const part = card.querySelector('[data-task-manager-review-part]')!;
    expect(part.querySelector('.tkm-review-key')!.textContent).toBe('to review');
    expect(part.querySelector('[data-task-manager-review-where]')!.textContent).toBe('huddle tab > row');
    const css = rule('./task-manager-bubble.css', '.hb');
    expect(css).toContain('border: 1px solid color-mix(in srgb, var(--_post) 45%');
    expect(css).toContain('background: color-mix(in srgb, var(--_post) 8%');
  });
});

describe('cursors', () => {
  test('the status field and icon are pointers, open or closed', () => {
    expect(rule('./TaskManagerRow.svelte', '.tkm-status')).toContain('cursor: pointer');
    expect(rule('./TaskManagerRow.svelte', '.tkm-tag')).toContain('cursor: pointer');
  });

  test('Shift over a post that would dismiss: the post wears the clear cursor with the close layer, and drops it with Shift', async () => {
    const item = { id: 1, list: 'all', text: 't', thread: [{ ...msg(10, 'claude', 'info', 'an info'), unread: true }] };
    const host = await draw(TaskManagerRowPosts as never, { item, parts: { posts: 'block', questions: false, reply: false } });
    const post = host.querySelector<HTMLElement>('[data-task-manager-post="10"]')!;
    const text = post.querySelector('.tkm-post-text')!;
    expect(post.classList.contains('tkm-posts-post--closing')).toBe(false);
    text.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, shiftKey: true }));
    await settle();
    expect(post.classList.contains('tkm-posts-post--closing')).toBe(true);
    expect(host.querySelector('[data-task-manager-post-close="10"]')).not.toBeNull();
    window.dispatchEvent(new KeyboardEvent('keyup', { shiftKey: false }));
    await settle();
    expect(post.classList.contains('tkm-posts-post--closing')).toBe(false);
    expect(rule('./TaskManagerRowPosts.svelte', '.tkm-posts > :global(.tkm-posts-post.tkm-posts-post--closing[data-task-manager-post])')).toMatch(/cursor:\s*url\("data:image\/svg\+xml[^)]*\) 12 12, not-allowed/);
  });
});

describe('an empty list', () => {
  test('the empty line takes the free room, so the control row and add row stay at the bottom', () => {
    expect(rule('./HuddleBody.svelte', '.hd-empty')).toContain('flex: 1 1 auto');
    expect(rule('./HuddleBody.svelte', '.hd')).toContain('flex-direction: column');
  });
});

describe('the open item', () => {
  test('threadTone: each Claude kind its own hue, other Claude the accent, the owner the quiet ink', () => {
    expect(threadTone({ author: 'claude', kind: 'question' })).toBe(KIND_COLORS.question.color);
    expect(threadTone({ author: 'claude', kind: 'info' })).toBe(KIND_COLORS.info.color);
    expect(threadTone({ author: 'claude', kind: 'attention' })).toBe(KIND_COLORS.look.color);
    expect(threadTone({ author: 'claude', kind: 'reply' })).toBe(KIND_COLORS.answer.color);
    expect(threadTone({ author: 'joe', kind: 'reply' })).toBe('var(--oc-text-secondary)');
  });

  test('the transcript wears the bubbles: a token per message, the owner on their own side with their own frame', async () => {
    const item = { id: 1, list: 'all', text: 't', state: 'open', thread: [msg(1, 'claude', 'info', 'fyi'), msg(2, 'joe', 'reply', 'ok'), msg(3, 'claude', 'attention', 'look')] };
    const host = await draw(HuddleThread as never, { item, closed: true });
    const style = (id: number) => host.querySelector<HTMLElement>(`[data-task-manager-message="${id}"]`)!.style.getPropertyValue('--_post');
    expect(style(1)).toBe(KIND_COLORS.info.color);
    expect(style(2)).toBe('var(--oc-text-secondary)');
    expect(style(3)).toBe(KIND_COLORS.look.color);
    expect(host.querySelector('[data-task-manager-message="2"]')!.classList.contains('hdt-msg--joe')).toBe(true);
    expect(rule('./task-manager-bubble.css', '.hb')).toContain('color-mix(in srgb, var(--_post) 8%');
    const joe = rule('./task-manager-bubble.css', '.hb--owner');
    expect(rule('./HuddleThread.svelte', '.hdt-list > :global(.hdt-msg--joe)')).toContain('align-self: flex-end');
    expect(joe).toContain('var(--oc-ground-raised)');
    expect(joe).toContain('inset -2px 0 0');
  });

  test('the item text is no separate lead block any more: the row carries no .hdr-desc rule', () => {
    expect(rule('./TaskManagerRow.svelte', '.hdr-desc')).toBe('');
  });
});
