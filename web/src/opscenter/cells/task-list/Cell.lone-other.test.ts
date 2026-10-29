/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const FORM = [{ id: 'pick', type: 'single', prompt: 'Which one?', required: true, other: true, options: [{ id: 'a', label: 'option a' }, { id: 'b', label: 'option b' }] }];
const ITEM = {
  id: 1, list: '1', text: 'pick a thing', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 1, seq: 1,
  deleted: false, status: 'question', title: null,
  thread: [{ id: 11, item_id: 1, author: 'claude', kind: 'question', text: 'pick a thing', questions: ['Which one?'], answered: false, created_at: 1_001, seq: 1, form: FORM, context: 'one rule' }],
};
const calls = vi.hoisted(() => [] as { path: string; method?: string; body?: unknown }[]);

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(init.body) : undefined });
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 1, groups: [{ list: '1', name: 'p', project_id: 1, revision: 1, items: [ITEM] }] };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '1', name: 'p', project_id: 1, items: 1, open: 1, review: 0, questions: 1, claude_seq: 1 }] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null, ok: true };
      if (path === '/swarm/roster') return { agents: [] };
      return {};
    },
  };
});
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Cell from './Cell.svelte';
import './meta';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { metaFor } from '../../engine/meta';

setLocale('en');
cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

/** Let the reads, the store and the effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} };
  calls.length = 0;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('pills only, no other pill or box, and the reply box under the question takes a typed reply', async () => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(Cell, { target: host, props: { width: 380, height: 600, meta: metaFor('task-list'), instance: 'hl', options: {} } });
  await settle();
  host.querySelector('[data-task-manager-list-row="1"] .hl-sum')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await settle();
  const open = host.querySelector('[data-task-manager-list-row="1"] [data-task-manager-list-open]')!;
  expect([...open.querySelectorAll('[data-ask-option]')].map((o) => o.textContent?.trim())).toEqual(['option a', 'option b']);
  expect(open.querySelector('[data-ask-other-open], [data-ask-other], [data-ask-form]')).toBeNull();
  const box = open.querySelector<HTMLTextAreaElement>('[data-huddle-reply="1"]')!;
  expect(box).not.toBeNull();
  box.value = 'something else entirely';
  box.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  open.querySelector<HTMLButtonElement>('.hdt-send')!.click();
  await vi.waitFor(() => expect(calls.some((c) => c.path === '/cplugs/huddle/items/1/messages' && c.method === 'POST' && (c.body as { text?: string }).text === 'something else entirely')).toBe(true));
});
