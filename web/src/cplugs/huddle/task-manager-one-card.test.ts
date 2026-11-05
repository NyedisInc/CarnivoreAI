/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const writes = vi.hoisted(() => ({ calls: [] as { path: string; body: unknown }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'POST') writes.calls.push({ path, body: JSON.parse(String(init.body ?? '{}')) });
      return Promise.resolve({});
    },
  };
});

import { readPost } from './huddle.svelte';
import { READ_PAUSE_MS, readPaused, resetReadPause, startReadPause } from './task-manager-read-pause';
import type { HuddleItem } from './huddle-model';
import HuddleReview from './HuddleReview.svelte';
import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';
import { reviewOf } from './huddle-review';
import { sectionOf } from './task-manager-status-sections';
import { actionableIdOf } from '../../opscenter/cells/task-manager-mk2/mk2-task-tabs';
import Mk2TaskTabs from '../../opscenter/cells/task-manager-mk2/Mk2TaskTabs.svelte';
import * as reviewModule from './huddle-review';

const msg = (id: number, kind = 'info') => ({ id, item_id: 1, author: 'claude', kind, text: `message ${id}`, created_at: id, seq: id, answered: false, unread: true });
const mk = (thread: unknown[], extra: Record<string, unknown> = {}): HuddleItem => ({
  id: 1, list: 'all', text: 't', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null, revision: 1,
  created_seq: 1, seq: 1, deleted: false, unread: true, info_unread: thread.filter((m) => (m as { kind: string }).kind === 'info').length, info_unseen: true, status: 'open', thread, ...extra,
}) as unknown as HuddleItem;
const sent = (): number[] => writes.calls.map((call) => (call.body as { message: number }).message).sort((a, b) => a - b);

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await tick(); flushSync(); };
beforeEach(() => { writes.calls.length = 0; resetReadPause(); });
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

describe('reading the one card reads only that message', () => {
  test('oneCard reads just its own post; older and newer unread posts stay', async () => {
    const item = mk([msg(3), msg(5, 'attention'), msg(9)]);
    await readPost(item, item.thread[1]!, { oneCard: true });
    expect(sent()).toEqual([5]);
    expect(item.thread.map((m) => m.unread)).toEqual([true, false, true]);
  });
  test('the plain row read (no oneCard) still reads just that post', async () => {
    const item = mk([msg(3), msg(9)]);
    await readPost(item, item.thread[1]!);
    expect(sent()).toEqual([9]);
    expect(item.thread[0]!.unread).toBe(true);
  });
});

describe('an info read in front of a pending question does not move the item', () => {
  test('its section stays needs you, before and after the optimistic read', async () => {
    const item = mk([msg(3), msg(4, 'question')], { status: 'question', needs_you: true, section: 'question' });
    expect(sectionOf(item)).toBe('needs_you');
    await readPost(item, item.thread[0]!, { oneCard: true });
    expect(item.thread[0]!.unread).toBe(false);
    expect(sectionOf(item)).toBe('needs_you');
    expect(actionableIdOf(item)).toBe(4);
  });
});

describe('the "N more" count under the card', () => {
  test('shows the cards in front, and nothing at 0', async () => {
    const draw = async (item: HuddleItem): Promise<HTMLElement> => {
      const host = document.createElement('div');
      document.body.appendChild(host);
      app = mount(Mk2TaskTabs as never, { target: host, props: { item } });
      await settle();
      return host;
    };
    const many = await draw(mk([msg(3), msg(4, 'question'), msg(6)], { status: 'question' }));
    expect(many.querySelector('[data-mk2-actionable]')?.getAttribute('data-mk2-actionable')).toBe('3');
    expect(many.querySelector('[data-mk2-more]')?.textContent?.trim()).toBe('2 more');
    unmount(app!); app = null; document.body.innerHTML = '';
    const one = await draw(mk([msg(3)]));
    expect(one.querySelector('[data-mk2-more]')).toBeNull();
  });
});

describe('the pause after a read', () => {
  test('the clock: ignored inside READ_PAUSE_MS, accepted after', () => {
    startReadPause(1000);
    expect(readPaused(1000 + READ_PAUSE_MS - 1)).toBe(true);
    expect(readPaused(1000 + READ_PAUSE_MS)).toBe(false);
  });
  test('a second read right after the first is ignored; once the pause passes it is read', async () => {
    const a = mk([msg(3)]);
    const b = mk([msg(8)], { id: 2 });
    await readPost(a, a.thread[0]!, { oneCard: true });
    await readPost(b, b.thread[0]!, { oneCard: true });
    expect(sent()).toEqual([3]);
    expect(b.thread[0]!.unread).toBe(true);
    resetReadPause();
    await readPost(b, b.thread[0]!, { oneCard: true });
    expect(sent()).toEqual([3, 8]);
  });
  test('a middle click on the card that slid under the pointer does nothing', async () => {
    const first = mk([msg(3)]);
    const second = mk([msg(8)], { id: 2 });
    const draw = async (item: HuddleItem): Promise<HTMLElement> => {
      const host = document.createElement('div');
      document.body.appendChild(host);
      app = mount(TaskManagerRowPosts as never, { target: host, props: { item, parts: { posts: 'block', questions: false, reply: false }, only: item.thread[0]!.id } });
      await settle();
      return host;
    };
    const middle = (host: HTMLElement, id: number): void => {
      host.querySelector(`[data-task-manager-post="${id}"]`)!.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true }));
    };
    middle(await draw(first), 3);
    middle(await draw(second), 8);
    await settle();
    expect(sent()).toEqual([3]);
  });
});

describe('the review card and the answered strip', () => {
  test('the answered strip and its helper are gone', async () => {
    expect('reviewAnswerOf' in reviewModule).toBe(false);
    const block = reviewOf({ id: 9, status: 'review', thread: [], review_description: 'fixed' } as never)!;
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleReview as never, { target: host, props: { id: 9, block, answer: { id: 2, summary: 'yes', hasMore: false, text: 'yes' } } });
    await settle();
    expect(host.querySelector('[data-task-manager-review-answer]')).toBeNull();
  });
});
