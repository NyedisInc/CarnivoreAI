/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const FORM = [
  { id: 'q1', type: 'single', prompt: 'how a session joins', required: true, options: [
    { id: 'a', label: 'instantly', recommended: true, reason: 'never interrupts' }, { id: 'b', label: 'restart now' }] },
  { id: 'q2', type: 'yes_no', prompt: 'allow studio now', required: true, recommend: { value: false } },
  { id: 'q3', type: 'single', prompt: 'where it shows', required: true, options: [
    { id: 'x', label: 'chat' }, { id: 'y', label: 'board', recommended: true }] },
];

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => (path === '/cplugs/huddle/questions/10'
      ? { item: 1, message: 10, typed: true, answered: false, answer_message_id: null, ask: { context: '', questions: FORM } }
      : {}),
  };
});

import ChatAskForm from './ChatAskForm.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}
async function click(el: Element | null): Promise<void> {
  expect(el).not.toBeNull();
  el!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await settle();
}
const chip = (host: HTMLElement, id: string): string | null =>
  host.querySelector(`[data-chat-ask-q="${id}"] [data-chat-ask-chip]`)?.textContent?.trim() ?? null;

test('rows show only his own answer, the star marks the rec, and accept rec fills only the unanswered', async () => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const message = { id: 10, item_id: 1, author: 'claude', kind: 'question', text: 'q', answered: false, created_at: 1, seq: 1, form: FORM };
  app = mount(ChatAskForm, { target: host, props: { item: { id: 1, list: 'all', text: 'q', title: '', thread: [message] } as never, message: message as never } });
  await settle();

  expect(['q1', 'q2', 'q3'].map((id) => chip(host, id))).toEqual([null, null, null]);
  await click(host.querySelector('[data-chat-ask-q="q1"] .hca-row'));
  expect(host.querySelector('[data-chat-ask-q="q1"] [data-ask-option="a"] [data-chat-ask-star]')).not.toBeNull();
  expect(host.querySelector('[data-chat-ask-q="q1"] [data-ask-option="b"] [data-chat-ask-star]')).toBeNull();
  await click(host.querySelector('[data-chat-ask-q="q1"] [data-ask-option="b"]'));
  expect(chip(host, 'q1')).toBe('restart now');
  expect(chip(host, 'q2')).toBeNull();

  await click(host.querySelector('[data-chat-ask-accept]'));
  expect(['q1', 'q2', 'q3'].map((id) => chip(host, id))).toEqual(['restart now', 'no', 'board']);
  expect(host.querySelector('[data-chat-ask-tally]')?.textContent).toContain('3/3');
});
