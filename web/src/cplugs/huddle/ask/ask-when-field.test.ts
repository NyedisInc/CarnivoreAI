/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ASK = {
  item: 1, message: 10, typed: true, answered: false, answer_message_id: null,
  ask: { context: '', questions: [{ id: 'q2', type: 'datetime', prompt: 'until when? (only for give it until)', required: false }] },
};
const calls = vi.hoisted(() => [] as { path: string; body: unknown }[]);

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { body?: unknown }) => {
      calls.push({ path, body: init?.body ? JSON.parse(init.body as string) : null });
      if (path === '/cplugs/huddle/questions/10') return ASK;
      if (path === '/cplugs/huddle/questions/10/answer') return { item: {}, message: { id: 11 } };
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
import TaskManagerAskForm from './TaskManagerAskForm.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

/** Let the read, the mount and the submit's queued save run. */
async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

beforeEach(() => {
  calls.length = 0;
  huddle.groups = null;
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'x', title: '', thread: [] }] } as never;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('a datetime question in the form', () => {
  test('draws a date and time picker and submits an ISO time with an offset', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel', onClose: vi.fn() } });
    await settle();
    const field = host.querySelector('[data-ask-field="q2"]') as HTMLInputElement;
    expect(field.tagName).toBe('INPUT');
    expect(field.type).toBe('datetime-local');
    field.value = '2026-11-03T09:30';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    (host.querySelector('[data-ask-submit]') as HTMLElement).click(); // safe: an unanswered form always draws its submit key
    await settle();
    const body = calls.find((c) => c.path.endsWith('/answer'))?.body as { answers: Record<string, { text?: string }> } | undefined;
    expect(body?.answers.q2?.text).toMatch(/^2026-11-03T09:30:00[+-]\d\d:\d\d$/);
  });
});
