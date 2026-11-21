/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const state = vi.hoisted(() => ({ ask: null as unknown, failAnswer: false, calls: [] as string[], bodies: [] as unknown[] }));
const CMD = { id: 'ho', type: 'single', prompt: 'Run the handoff', required: true, other: true, command: { text: '~/.handoff/handoff x', lang: 'bash' }, options: [{ id: 'ran', label: 'ran it' }, { id: 'failed', label: 'failed' }] };
const PLAIN = { ...CMD, id: 'pl', command: undefined, other: false };
const YN = { id: 'yn', type: 'yes_no', prompt: 'Close it?', required: true, labels: ['close', 'keep'] };
const MULTI = { id: 'mu', type: 'multi', prompt: 'Which?', required: true, options: [{ id: 'a', label: 'a' }] };
const TEXT = { id: 'tx', type: 'short_text', prompt: 'Why?', required: true };
const make = (questions: unknown[]) => ({ item: 1, message: 10, typed: true, answered: false, answer_message_id: null, ask: { context: '', questions } });
const post = (form: unknown[], extra: Record<string, unknown> = {}) => ({ id: 10, item_id: 1, author: 'claude', kind: 'question', text: 'q', context: 'why we ask', questions: ['q'], answered: false, created_at: 1, seq: 1, form, ...extra });

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { body?: string }) => {
      state.calls.push(path);
      if (path === '/cplugs/huddle/questions/10') return state.ask;
      if (path === '/cplugs/huddle/questions/10/answer') {
        if (state.failAnswer) throw new Error('server said no');
        state.bodies.push(JSON.parse(init?.body ?? '{}'));
        return { item: {}, message: { id: 11 } };
      }
      if (path === '/cplugs/huddle/send') return { results: [{ list: 'all', status: 'sent' }] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [] };
      return {};
    },
  };
});

import { huddle } from '../huddle.svelte';
import { cplugEnablement } from '../../host/enablement.svelte';
import TaskManagerRowPosts from '../TaskManagerRowPosts.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;
let detach: () => void = () => {};
const PARTS = { extras: true, description: true, latest: true, questions: true, reply: false } as never;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}
async function openRow(message: unknown): Promise<{ host: HTMLElement; reached: () => number }> {
  const host = document.createElement('div');
  let reached = 0;
  const count = (): void => { reached += 1; };
  document.addEventListener('click', count);
  detach = () => document.removeEventListener('click', count);
  document.body.appendChild(host);
  const item = { id: 1, list: 'all', text: 'handoff', title: '', created_by: 'claude', created_seq: 1, status: 'question', thread: [message] };
  app = mount(TaskManagerRowPosts, { target: host, props: { item: item as never, parts: PARTS } });
  await settle();
  return { host, reached: () => reached };
}
async function click(el: HTMLElement, shiftKey = false): Promise<void> {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey }));
  await settle();
}

beforeEach(() => {
  state.calls.length = 0;
  state.bodies.length = 0;
  state.ask = make([CMD]);
  huddle.groups = null;
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'handoff', title: '', thread: [] }] } as never;
});
afterEach(() => {
  detach();
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const DISMISSED = [{ answers: { ho: { skipped: true, dismissed: true } } }];

describe('question card close', () => {
  test('shift-click on the card body dismisses and does not reach the row', async () => {
    const { host, reached } = await openRow(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-task-manager-post="10"] [data-ask-inline-lead]')!, true);
    expect(state.bodies).toEqual(DISMISSED);
    expect(reached()).toBe(0);
  });

  test('clicking the icon dismisses and does not reach the row', async () => {
    const { host, reached } = await openRow(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-task-manager-question-dismiss="10"]')!);
    expect(state.bodies).toEqual(DISMISSED);
    expect(reached()).toBe(0);
  });

  test('the card carries the shift-click tooltip and the icon its own label', async () => {
    const { host } = await openRow(post([CMD]));
    expect(host.querySelector('[data-task-manager-post="10"]')!.getAttribute('title')).toContain('shift-click anywhere on it');
    expect(host.querySelector('[data-task-manager-question-dismiss="10"]')!.getAttribute('aria-label')).toContain('dismiss');
  });

  test('a plain click on the card body does nothing, a plain pill click still answers', async () => {
    const { host } = await openRow(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-task-manager-post="10"] [data-ask-inline-lead]')!);
    expect(state.bodies).toEqual([]);
    await click(host.querySelector<HTMLElement>('[data-ask-option="ran"]')!);
    expect(state.bodies).toEqual([{ answers: { ho: { choice: 'ran' } } }]);
  });

  test('a shift-click on the prompt dismisses once, not twice', async () => {
    const { host } = await openRow(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-ask-inline-prompt]')!, true);
    expect(state.bodies).toEqual(DISMISSED);
  });

  test('the icon swaps to the close glyph and the card dims on icon hover, and on Shift over the card', async () => {
    const { host } = await openRow(post([CMD]));
    const card = host.querySelector<HTMLElement>('[data-task-manager-post="10"]')!;
    const icon = host.querySelector<HTMLElement>('[data-task-manager-question-dismiss="10"]')!;
    const glyph = (): string => icon.innerHTML;
    const resting = glyph();
    expect(card.classList.contains('tkm-posts-post--closing')).toBe(false);
    icon.dispatchEvent(new PointerEvent('pointerenter'));
    await settle();
    expect(glyph()).not.toBe(resting);
    expect(card.classList.contains('tkm-posts-post--closing')).toBe(true);
    expect(card.querySelector('[data-task-manager-post-close="10"]')).not.toBeNull();
    icon.dispatchEvent(new PointerEvent('pointerleave'));
    await settle();
    expect(glyph()).toBe(resting);
    card.querySelector('[data-ask-inline-lead]')!.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, shiftKey: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { shiftKey: true }));
    await settle();
    expect(card.classList.contains('tkm-posts-post--closing')).toBe(true);
    expect(glyph()).not.toBe(resting);
  });
});
