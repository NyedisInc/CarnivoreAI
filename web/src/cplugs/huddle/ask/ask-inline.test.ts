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
        if (state.failAnswer) throw Object.assign(new Error('server said no'), { status: 400 });
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
import { dismissPayload, inlineQuestion, type AskQuestion } from './ask-model';
import TaskManagerAsk from '../TaskManagerAsk.svelte';
import TaskManagerAskForm from './TaskManagerAskForm.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}
async function open(message: unknown, folded = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerAsk, { target: host, props: { message: message as never, folded } });
  await settle();
  return host;
}
async function click(el: HTMLElement, shiftKey = false): Promise<void> {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey }));
  await settle();
}

beforeEach(() => {
  state.calls.length = 0;
  state.bodies.length = 0;
  state.failAnswer = false;
  huddle.groups = null;
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'handoff', title: '', thread: [] }] } as never;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('inline vs popup', () => {
  test('inlineQuestion takes one single (with options) or one yes_no, nothing else', () => {
    expect(inlineQuestion([CMD as AskQuestion])).not.toBeNull();
    expect(inlineQuestion([PLAIN as AskQuestion])).not.toBeNull();
    expect(inlineQuestion([YN as AskQuestion])).not.toBeNull();
    expect(inlineQuestion([MULTI as AskQuestion])).toBeNull();
    expect(inlineQuestion([TEXT as AskQuestion])).toBeNull();
    expect(inlineQuestion([YN, MULTI] as AskQuestion[])).toBeNull();
    expect(inlineQuestion([YN, CMD] as AskQuestion[])?.id).toBe('ho');
    expect(inlineQuestion([{ ...CMD, options: [] } as AskQuestion])).toBeNull();
    expect(inlineQuestion(undefined)).toBeNull();
  });

  test('a lone single draws context, command and pills in the thread with no popup form', async () => {
    const host = await open(post([CMD]));
    expect(host.querySelector('[data-ask-inline="10"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-command]')).not.toBeNull();
    expect(host.querySelectorAll('[data-ask-option]').length).toBe(2);
    expect(host.querySelector('[data-ask-form]')).toBeNull();
    expect(host.textContent).toContain('why we ask');
  });

  test('a yes/no draws two pills with its own labels', async () => {
    const host = await open(post([YN]));
    const pills = [...host.querySelectorAll('[data-ask-option]')].map((p) => p.textContent?.trim());
    expect(pills).toEqual(['close', 'keep']);
  });

  test('several questions, multi and text keep the form; a multi-question row keeps its bubble', async () => {
    expect((await open(post([YN, MULTI]))).querySelector('[data-ask-form]')).not.toBeNull();
    document.body.innerHTML = '';
    expect((await open(post([MULTI]))).querySelector('[data-ask-inline]')).toBeNull();
    document.body.innerHTML = '';
    const row = await open(post([YN, MULTI]), true);
    expect(row.querySelector('[data-ask-inline]')).toBeNull();
    expect(row.querySelector('[data-ask-bubble]')).not.toBeNull();
  });

  test('a lone single on the ROW draws inline: lead line only, command, pills, no bubble; a pill answers', async () => {
    state.ask = make([CMD]);
    const row = await open(post([CMD], { context: 'first line\nsecond line' }), true);
    expect(row.querySelector('[data-ask-bubble]')).toBeNull();
    expect(row.querySelector('[data-ask-inline-lead]')!.textContent).toContain('first line');
    expect(row.textContent).not.toContain('second line');
    expect(row.querySelector('[data-task-manager-command]')).not.toBeNull();
    await click(row.querySelector<HTMLElement>('[data-ask-option="ran"]')!);
    expect(state.bodies).toEqual([{ answers: { ho: { choice: 'ran' } } }]);
  });

  test('shift-click on a row pill dismisses', async () => {
    state.ask = make([CMD]);
    const row = await open(post([CMD]), true);
    await click(row.querySelector<HTMLElement>('[data-ask-option="ran"]')!, true);
    expect(state.bodies).toEqual([{ answers: { ho: { skipped: true, dismissed: true } } }]);
  });
});

describe('pill submit', () => {
  test('one tap posts the popup payload to the same route and shows the chosen answer', async () => {
    state.ask = make([CMD]);
    const host = await open(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-ask-option="failed"]')!);
    expect(state.bodies).toEqual([{ answers: { ho: { choice: 'failed' } } }]);
    await vi.waitFor(() => expect(host.querySelector('[data-ask-option]')).toBeNull());
    expect(host.querySelector('[data-ask-answer="ho"]')!.textContent).toContain('failed');
  });

  test('a yes/no pill posts value true / false', async () => {
    state.ask = make([YN]);
    const host = await open(post([YN]));
    await click(host.querySelector<HTMLElement>('[data-ask-option="no"]')!);
    expect(state.bodies).toEqual([{ answers: { yn: { value: false } } }]);
  });

  test('a failed submit restores the pills and shows the error', async () => {
    state.ask = make([CMD]);
    state.failAnswer = true;
    const host = await open(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-ask-option="ran"]')!);
    await vi.waitFor(() => expect(host.querySelector('[data-ask-error]')).not.toBeNull());
    expect(host.querySelector('[data-ask-sending]')).toBeNull();
    expect(host.querySelector<HTMLButtonElement>('[data-ask-option="ran"]')!.disabled).toBe(false);
  });

  test('an answered post draws no pills and the stored answer in words', async () => {
    huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'h', title: '', thread: [{ id: 11, item_id: 1, author: 'joe', kind: 'answer', answers_to: 10, answers: { ho: { choice: 'ran', label: 'ran it', prompt: 'p' } } }] }] } as never;
    const host = await open(post([CMD], { answered: true }));
    expect(host.querySelector('[data-ask-option]')).toBeNull();
    expect(host.querySelector('[data-ask-answer="ho"]')!.textContent).toContain('ran it');
  });

  test('a question answered by the owner\'s chat comment says so (item 492)', async () => {
    huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'h', title: '', thread: [{ id: 11, item_id: 1, author: 'joe', kind: 'reply', text: 'do x', answers_to: 10, freeform: true }] }] } as never;
    const host = await open(post([CMD], { answered: true }));
    expect(host.querySelector('[data-ask-option]')).toBeNull();
    expect(host.querySelector('[data-ask-answer="ho"]')!.textContent).toBe('answered by your comment');
  });

  test('a single that allows other draws no other pill: the reply box under the post is the other (#1797)', async () => {
    state.ask = make([CMD]);
    const host = await open(post([CMD]));
    expect(host.querySelector('[data-ask-other-open]')).toBeNull();
    expect(host.querySelectorAll('[data-ask-option]').length).toBe(2);
    expect(state.bodies).toEqual([]);
  });
});

describe('shift-click dismiss', () => {
  test('dismissPayload skips every question and marks it dismissed', () => {
    expect(dismissPayload([CMD, YN] as AskQuestion[])).toEqual({ ho: { skipped: true, dismissed: true }, yn: { skipped: true, dismissed: true } });
  });

  test('shift-click on a pill dismisses through the same route and reads dismissed', async () => {
    state.ask = make([CMD]);
    const host = await open(post([CMD]));
    await click(host.querySelector<HTMLElement>('[data-ask-option="ran"]')!, true);
    expect(state.bodies).toEqual([{ answers: { ho: { skipped: true, dismissed: true } } }]);
    await vi.waitFor(() => expect(host.querySelector('[data-ask-answer="ho"]')!.textContent).toContain('dismissed'));
  });

  test('shift-click on the row bubble button dismisses without opening', async () => {
    state.ask = make([YN, MULTI]);
    const host = await open(post([YN, MULTI]), true);
    await click(host.querySelector<HTMLElement>('[data-ask-open]')!, true);
    expect(state.bodies).toEqual([{ answers: { yn: { skipped: true, dismissed: true }, mu: { skipped: true, dismissed: true } } }]);
  });

  test('shift-click on the popup title strip dismisses and closes', async () => {
    state.ask = make([CMD, YN]);
    const host = document.createElement('div');
    document.body.appendChild(host);
    const closed = vi.fn();
    app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel', onClose: closed } });
    await settle();
    await click(host.querySelector<HTMLElement>('[data-ask-strip]')!, true);
    expect(state.bodies).toEqual([{ answers: { ho: { skipped: true, dismissed: true }, yn: { skipped: true, dismissed: true } } }]);
    await vi.waitFor(() => expect(closed).toHaveBeenCalled());
  });
});

describe('buttons are the base button (#1710)', () => {
  test('inline pills and yes / no keys carry data-btn and no hand-drawn button class', async () => {
    for (const form of [CMD, YN]) {
      const host = await open(post([form]));
      const keys = [...host.querySelectorAll<HTMLElement>('[data-ask-option], [data-ask-pick]')];
      expect(keys.length).toBeGreaterThan(0);
      expect(keys.every((k) => k.getAttribute('data-btn') !== null)).toBe(true);
      expect(host.querySelector('.hdq-opt, .hdq-link, .hdq-tool, .hdq-seg')).toBeNull();
      unmount(app!);
      app = null;
      document.body.innerHTML = '';
    }
  });
});
