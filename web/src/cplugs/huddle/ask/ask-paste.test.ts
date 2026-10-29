/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ASK = {
  item: 1, message: 10, typed: true, answered: false, answer_message_id: null,
  ask: { context: '', questions: [
    { id: 'why', type: 'short_text', prompt: 'Why?', required: false },
    { id: 'more', type: 'long_text', prompt: 'More?', required: false },
  ] },
};
const calls = vi.hoisted(() => [] as { path: string; body: unknown }[]);

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { body?: unknown }) => {
      const isForm = init?.body instanceof FormData;
      calls.push({ path, body: isForm || !init?.body ? null : JSON.parse(init.body as string) });
      if (path === '/cplugs/huddle/questions/10') return ASK;
      if (path === '/cplugs/huddle/items/1/files') return { id: `f${calls.length}`, name: 'shot.png', mime: 'image/png', size: 4 };
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

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}
async function open(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel', onClose: vi.fn() } });
  await settle();
  return host;
}
async function paste(field: Element): Promise<Event> {
  const file = new File(['png!'], 'shot.png', { type: 'image/png' });
  const event = new Event('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clipboardData', { value: { files: [file], items: [], types: ['Files'] } });
  field.dispatchEvent(event);
  await settle();
  return event;
}
const answerBody = (): { answers: Record<string, { text?: string; file_ids?: string[] }> } | undefined =>
  calls.find((c) => c.path.endsWith('/answer'))?.body as never;

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

describe('a pasted screenshot in the form', () => {
  test('the anything else box takes it: a chip shows before submit and the submit sends its id', async () => {
    const host = await open();
    const event = await paste(host.querySelector('[data-ask-extra-field]')!);
    expect(event.defaultPrevented).toBe(true);
    expect(host.querySelectorAll('[data-ask-paste="_extra"] [data-task-manager-pending-file]').length).toBe(1);
    expect(calls.some((c) => c.path === '/cplugs/huddle/items/1/files')).toBe(true);
    (host.querySelector('[data-ask-submit]') as HTMLElement).click();
    await settle();
    expect(answerBody()?.answers._extra?.file_ids).toHaveLength(1);
  });

  test('a short text answer takes it too, and the remove key drops the chip so nothing is sent', async () => {
    const host = await open();
    await paste(host.querySelector('[data-ask-field="why"]')!);
    expect(host.querySelectorAll('[data-ask-paste="why"] [data-task-manager-pending-file]').length).toBe(1);
    (host.querySelector('[data-ask-paste="why"] [data-task-manager-pending-remove]') as HTMLElement).click();
    await settle();
    expect(host.querySelector('[data-ask-paste="why"] [data-task-manager-pending-file]')).toBeNull();
    (host.querySelector('[data-ask-submit]') as HTMLElement).click();
    await settle();
    expect(answerBody()?.answers.why).toBeUndefined();
  });

  test('a long text answer rides its file as file_ids beside its text', async () => {
    const host = await open();
    const field = host.querySelector('[data-ask-field="more"]') as HTMLTextAreaElement;
    field.value = 'see shot';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await paste(field);
    (host.querySelector('[data-ask-submit]') as HTMLElement).click();
    await settle();
    expect(answerBody()?.answers.more).toMatchObject({ text: 'see shot', file_ids: [expect.any(String)] });
  });
});
