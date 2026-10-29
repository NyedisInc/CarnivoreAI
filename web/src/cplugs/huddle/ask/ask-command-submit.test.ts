/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const state = vi.hoisted(() => ({ ask: null as unknown, failAnswer: false, calls: [] as string[] }));
const CMD = { id: 'ho', type: 'single', prompt: 'Run the handoff', required: true, command: { text: '~/.handoff/handoff x', lang: 'bash' }, options: [{ id: 'ran', label: 'ran it' }, { id: 'failed', label: 'failed' }] };
const YN = { id: 'yn', type: 'yes_no', prompt: 'Also close?', required: true, labels: ['close', 'keep'] };
const make = (questions: unknown[]) => ({ item: 1, message: 10, typed: true, answered: false, answer_message_id: null, ask: { context: '', questions } });

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      state.calls.push(path);
      if (path === '/cplugs/huddle/questions/10') return state.ask;
      if (path === '/cplugs/huddle/questions/10/answer') {
        if (state.failAnswer) throw new Error('server said no');
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
import TaskManagerAskForm from './TaskManagerAskForm.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}
async function open(closed = vi.fn()): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel', onClose: closed } });
  await settle();
  return host;
}
async function click(el: HTMLElement): Promise<void> {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await settle();
}

beforeEach(() => {
  state.calls.length = 0;
  state.failAnswer = false;
  huddle.groups = null;
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'handoff', title: '', thread: [] }] } as never;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('command question in the form', () => {
  test('the command is inside the question box description area, not a block above the options', async () => {
    state.ask = make([CMD]);
    const host = await open();
    const command = host.querySelector('[data-ask-command="ho"]')!;
    expect(command.closest('fieldset')!.dataset.qid).toBe('ho');
    expect(command.parentElement!.classList.contains('hdq-help')).toBe(true);
    const pills = host.querySelector('.hdq-pills')!;
    expect(command.compareDocumentPosition(pills) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test('a tap on the only question submits at once and closes, with no send press', async () => {
    state.ask = make([CMD]);
    const closed = vi.fn();
    const host = await open(closed);
    await click(host.querySelector<HTMLElement>('[data-ask-option="failed"]')!);
    expect(state.calls).toContain('/cplugs/huddle/questions/10/answer');
    await vi.waitFor(() => expect(closed).toHaveBeenCalled());
  });

  test('an older mixed form draws the command question alone, and a pill tap answers at once, skipping the hidden sibling (#1797)', async () => {
    state.ask = make([CMD, YN]);
    const closed = vi.fn();
    const host = await open(closed);
    expect(host.querySelector('[data-ask-pick="yes"]')).toBeNull();
    expect(host.querySelector('[data-ask-extra-field]')).toBeNull();
    expect(host.querySelectorAll('[data-qid]').length).toBe(1);
    await click(host.querySelector<HTMLElement>('[data-ask-option="ran"]')!);
    expect(state.calls).toContain('/cplugs/huddle/questions/10/answer');
    await vi.waitFor(() => expect(closed).toHaveBeenCalled());
  });

  test('a refused submit closes the form at once, then takes the answer back and says why in the huddle notice', async () => {
    state.ask = make([CMD]);
    state.failAnswer = true;
    const closed = vi.fn();
    const host = await open(closed);
    await click(host.querySelector<HTMLElement>('[data-ask-option="ran"]')!);
    expect(closed).toHaveBeenCalled();
    await vi.waitFor(() => expect(huddle.notice).not.toBe(''));
    expect(host.querySelector('[data-ask-sending]')).toBeNull();
  });
});
