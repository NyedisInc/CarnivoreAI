/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { postKindOf, postTone, rowFeed, unreadCount, unreadPosts } from './task-manager-posts';
import { threadTone } from './task-manager-bubbles';
import TaskManagerAnswerBox from './TaskManagerAnswerBox.svelte';
import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';
import { rowParts } from './huddle-density';

const quoted = { id: 5, text: 'can we ship friday?' };
const answer = { id: 6, item_id: 1, author: 'claude', kind: 'answer', text: 'yes, **friday** works', answered: false, created_at: 6, seq: 6, unread: true, quote: quoted };
const ask = { id: 5, item_id: 1, author: 'joe', kind: 'reply', text: 'can we ship friday?', answered: false, created_at: 5, seq: 5 };
const item = { id: 1, list: 'all', kind: '', created_by: 'joe', status: 'working', text: 't', created_seq: 0, info_unread: 1, thread: [ask, answer] } as never;

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('an answer is an info with a quote', () => {
  test('counts and reads as an info, wears the info token, is not a question', () => {
    expect(postKindOf(answer as never)).toBe('info');
    expect(unreadPosts(item).map((m) => m.id)).toEqual([6]);
    expect(unreadCount({ thread: [answer] } as never, 'info')).toBe(1);
    expect(threadTone(answer as never)).toBe('var(--oc-orange)');
    expect(postTone(answer as never).color).toBe('var(--oc-orange)');
    expect(postTone({ author: 'claude', kind: 'info' } as never).color).toBe('var(--oc-violet)');
    expect(postKindOf({ author: 'joe', kind: 'answer' } as never)).toBeNull();
  });

  test('the row feed carries the unread answer, and not Joe\'s question it quotes', () => {
    expect(rowFeed(item).map((m) => m.id)).toEqual([6]);
    expect(rowFeed({ ...(item as object), thread: [ask, { ...answer, unread: false }] } as never)).toEqual([]);
  });

  test('the box shows the quote muted above the answer, and just the answer when there is no quote', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAnswerBox, { target: host, props: { message: answer as never } });
    flushSync(); await tick();
    expect(host.querySelector('[data-task-manager-answer-quote]')!.textContent).toBe('can we ship friday?');
    expect(host.querySelector('[data-task-manager-answer-body]')!.textContent).toContain('friday works');
    expect(host.querySelector('[data-task-manager-answer-body] strong')!.textContent).toBe('friday');
    const order = [...host.querySelector('[data-task-manager-answer]')!.children].map((c) => c.getAttribute('data-task-manager-answer-quote') !== null ? 'quote' : 'body');
    expect(order).toEqual(['quote', 'body']);
    unmount(app);
    app = mount(TaskManagerAnswerBox, { target: host, props: { message: { ...answer, quote: undefined } as never } });
    flushSync(); await tick();
    expect(host.querySelector('[data-task-manager-answer-quote]')).toBeNull();
  });

  test('on the row it is one info-style post with its read key, the quote inside, and no question block', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerRowPosts, { target: host, props: { item: item as never, parts: rowParts('normal', item) as never } });
    flushSync(); await tick();
    const post = host.querySelector('[data-task-manager-post="6"]')!;
    expect(post.getAttribute('data-task-manager-post-kind')).toBe('answer');
    expect(post.querySelector('[data-task-manager-post-read="6"]')).not.toBeNull();
    expect(post.querySelector('[data-task-manager-answer-quote]')!.textContent).toBe('can we ship friday?');
    expect(host.querySelector('[data-task-manager-questions]')).toBeNull();
  });
});
