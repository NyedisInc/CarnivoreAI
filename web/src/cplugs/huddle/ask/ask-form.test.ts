/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ASK = {
  item: 1, message: 10, typed: true, answered: false, answer_message_id: null,
  ask: { context: 'seven rulings', questions: [
    { id: 'i54', type: 'yes_no', prompt: 'Close #54?', required: true, labels: ['close', 'keep'], recommend: { value: true, reason: 'carries the fix' } },
    { id: 'pick', type: 'single', prompt: 'Which one?', required: true, other: true, options: [
      { id: 'fold', label: 'fold it', recommended: true, reason: 'one renderer' }, { id: 'link', label: 'cross-link' }] },
    { id: 'tags', type: 'multi', prompt: 'Where?', required: false, options: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }] },
    { id: 'ord', type: 'rank', prompt: 'Order', required: true, options: [{ id: 'k', label: 'K' }, { id: 'm', label: 'M' }], recommend: { order: ['m', 'k'], reason: 'm first' } },
    { id: 'why', type: 'short_text', prompt: 'Why?', required: false },
  ] },
};
const calls = vi.hoisted(() => [] as { path: string; body: unknown }[]);

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { body?: string }) => {
      calls.push({ path, body: init?.body ? JSON.parse(init.body) : null });
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
import TaskManagerAskPanel from './TaskManagerAskPanel.svelte';
import TaskManagerAsk from '../TaskManagerAsk.svelte';
import { askFold, hasFormAsk, hasNumberedAsk, rowFeed } from '../task-manager-posts';
import { payloadOf } from './ask-model';

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

const q = (host: HTMLElement, sel: string): HTMLElement => host.querySelector<HTMLElement>(sel)!;
async function click(el: HTMLElement, init: MouseEventInit = {}): Promise<void> {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, ...init }));
  await settle();
}
async function key(el: HTMLElement, k: string, init: KeyboardEventInit = {}): Promise<void> {
  el.focus();
  el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...init }));
  await settle();
}

beforeEach(() => {
  calls.length = 0;
  huddle.groups = null;
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'issue rulings', title: '', thread: [] }] } as never;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the footer centers the count between its icons', () => {
  test('take all, the count and send sit in a three-column grid whose side columns are equal, the count in the middle', async () => {
    const host = await open();
    const foot = q(host, '.hdq-foot');
    expect([...foot.children].map((c) => (c as HTMLElement).dataset.askTakeAll !== undefined ? 'take' : (c as HTMLElement).dataset.askProgress !== undefined ? 'count' : c.querySelector('[data-ask-submit]') ? 'send' : '?')).toEqual(['take', 'count', 'send']);
    const css = readFileSync(resolve(process.cwd(), 'src/cplugs/huddle/ask/ask-form.css'), 'utf8');
    expect(css).toMatch(/\.hdq-foot \{[^}]*display: grid;[^}]*grid-template-columns: minmax\(0, 1fr\) auto minmax\(0, 1fr\);[^}]*align-items: center;/);
    expect(css).toMatch(/\.hdq-foot \.hdq-count \{[^}]*grid-column: 2;[^}]*justify-self: center;[^}]*align-self: center;/);
    expect(css).toMatch(/\.hdq-foot > \[data-ask-take-all\] \{[^}]*grid-column: 1;/);
    expect(css).toMatch(/\.hdq-foot-end \{[^}]*grid-column: 3;[^}]*justify-self: end;/);
    expect(css).not.toMatch(/\.hdq-foot[^{]*\{[^}]*margin-(inline|left): auto/);
  });
});

describe('the form', () => {
  test('draws the context, every question as a fieldset, and a submit that names what is left', async () => {
    const host = await open();
    expect(q(host, '.hdq-context').textContent).toBe('seven rulings');
    expect([...host.querySelectorAll('fieldset')].map((f) => f.dataset.qid)).toEqual(['i54', 'pick', 'tags', 'ord', 'why']);
    expect(q(host, '.hdq-name').textContent).toBe('issue rulings');
    expect(q(host, '[data-ask-progress]').textContent).toMatch(/0 \/ 5.*3 required/);
    const submit = q(host, '[data-ask-submit]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(submit.getAttribute('title')).toBe('3 required left');
    expect(q(host, '[data-ask-option="fold"]').getAttribute('aria-checked')).toBe('false');
    expect(q(host, '[data-ask-option="fold"]').textContent).toContain('rec');
    expect(host.textContent).toContain('one renderer');
  });

  test('take recommendation and take all fill only the answers Claude recommended, and submit enables', async () => {
    const host = await open();
    await click(q(host, '[data-ask-take="i54"]'));
    expect(q(host, '[data-qid="i54"] [data-ask-pick="yes"]').getAttribute('aria-checked')).toBe('true');
    expect(q(host, '[data-qid="i54"] [data-ask-take]')).toBeNull();
    await click(q(host, '[data-ask-take-all]'));
    expect(q(host, '[data-ask-option="fold"]').getAttribute('aria-checked')).toBe('true');
    expect(q(host, '[data-qid="ord"] [data-ask-row]')!.getAttribute('data-ask-row')).toBe('m');
    expect(q(host, '[data-ask-progress]').textContent).toMatch(/3 \/ 5/);
    expect((q(host, '[data-ask-submit]') as HTMLButtonElement).disabled).toBe(false);
  });

  test('submit posts one payload keyed by question id, tells claude, and closes', async () => {
    const closed = vi.fn();
    const host = await open(closed);
    await click(q(host, '[data-ask-take-all]'));
    await click(q(host, '[data-qid="tags"] [data-ask-option="b"]'));
    await click(q(host, '[data-ask-add-note="i54"]'));
    const note = q(host, '[data-ask-note="i54"]') as HTMLInputElement;
    note.value = 'after the release';
    note.dispatchEvent(new Event('input', { bubbles: true }));
    await click(q(host, '[data-ask-submit]'));
    const post = calls.find((c) => c.path.endsWith('/answer'))!;
    expect(post.body).toEqual({ answers: {
      i54: { value: true, note: 'after the release' }, pick: { choice: 'fold' }, tags: { choices: ['b'] }, ord: { order: ['m', 'k'] } } });
    const tell = calls.find((c) => c.path === '/cplugs/huddle/send');
    expect(tell).toBeDefined();
    expect((tell!.body as { queue?: boolean }).queue).toBe(true);
    await vi.waitFor(() => expect(closed).toHaveBeenCalled());
  });

  test('shift no longer holds the tell (Joe, 2026-10-12): a Shift-submit saves AND queues the tell; the label never reads hold', async () => {
    const host = await open();
    await click(q(host, '[data-ask-take-all]'));
    const submit = q(host, '[data-ask-submit]');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
    await settle();
    expect(submit.getAttribute('title')).toBe('submit');
    await click(submit, { shiftKey: true });
    expect(calls.some((c) => c.path.endsWith('/answer'))).toBe(true);
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/cplugs/huddle/send')).toBe(true));
    const tell = calls.find((c) => c.path === '/cplugs/huddle/send')!;
    expect((tell.body as { queue?: boolean }).queue).toBe(true);
  });
});

describe('the keyboard', () => {
  test('Y and N answer a yes/no, a digit picks the nth option, R takes the recommendation', async () => {
    const host = await open();
    await key(q(host, '[data-qid="i54"] [data-ask-pick="yes"]'), 'n');
    expect(q(host, '[data-qid="i54"] [data-ask-pick="no"]').getAttribute('aria-checked')).toBe('true');
    await key(q(host, '[data-qid="pick"] [data-ask-option="fold"]'), '2');
    expect(q(host, '[data-ask-option="link"]').getAttribute('aria-checked')).toBe('true');
    await key(q(host, '[data-qid="tags"] [data-ask-option="a"]'), '2');
    expect(q(host, '[data-qid="tags"] [data-ask-option="b"]').getAttribute('aria-checked')).toBe('true');
    await key(q(host, '[data-qid="ord"] [data-ask-row="m"]'), 'r');
  });

  test('arrow keys move between options; Alt+PageDown jumps to the next question', async () => {
    const host = await open();
    const fold = q(host, '[data-qid="pick"] [data-ask-option="fold"]');
    await key(fold, 'ArrowDown');
    expect(document.activeElement).toBe(q(host, '[data-qid="pick"] [data-ask-option="link"]'));
    await key(fold, 'PageDown', { altKey: true });
    expect(document.activeElement?.closest('fieldset')?.dataset.qid).toBe('tags');
  });

  test('a rank: Space grabs, Down moves, Escape puts it back; Alt+Up moves without a grab; Up/Down keys move', async () => {
    const host = await open();
    const row = (id: string): HTMLElement => q(host, `[data-qid="ord"] [data-ask-row="${id}"]`);
    const order = (): string[] => [...host.querySelectorAll('[data-qid="ord"] [data-ask-row]')].map((r) => r.getAttribute('data-ask-row')!);
    expect(order()).toEqual(['m', 'k']);
    await key(row('m'), ' ');
    await key(row('m'), 'ArrowDown');
    expect(order()).toEqual(['k', 'm']);
    await key(row('m'), 'Escape');
    expect(order()).toEqual(['m', 'k']);
    await key(row('k'), 'ArrowUp', { altKey: true });
    expect(order()).toEqual(['k', 'm']);
    await click(q(host, '[data-ask-down="k"]'));
    expect(order()).toEqual(['m', 'k']);
  });

  test('Ctrl+Enter submits when nothing is left, and is refused while a required is open', async () => {
    const host = await open();
    await key(q(host, '[data-qid="i54"] [data-ask-pick="yes"]'), 'Enter', { ctrlKey: true });
    expect(calls.some((c) => c.path.endsWith('/answer'))).toBe(false);
    await click(q(host, '[data-ask-take-all]'));
    await key(q(host, '[data-qid="i54"] [data-ask-pick="yes"]'), 'Enter', { ctrlKey: true, shiftKey: true });
    expect(calls.some((c) => c.path.endsWith('/answer'))).toBe(true);
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/cplugs/huddle/send')).toBe(true)); // no longer holds
  });
});

describe('anything else', () => {
  test('is an always-present optional box that never blocks submit and rides the payload as _extra', async () => {
    const host = await open();
    const box = q(host, '[data-ask-extra-field]') as HTMLTextAreaElement;
    expect(q(host, '[data-ask-extra] label').textContent).toBe('anything else');
    await click(q(host, '[data-ask-take-all]'));
    box.value = '  also check the docs  ';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(payloadOf(ASK.ask.questions as never, {}, '  also check the docs  ')._extra).toEqual({ text: 'also check the docs' });
    expect(payloadOf(ASK.ask.questions as never, {}, '   ')._extra).toBeUndefined();
    await click(q(host, '[data-ask-submit]'));
    const sent = calls.find((c) => c.path.endsWith('/answer'));
    expect((sent?.body as { answers: Record<string, unknown> }).answers._extra).toEqual({ text: 'also check the docs' });
  });

  test('is read-only in the answered view when it had words, and absent when it had none', async () => {
    huddle.groups = null;
    huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'x', title: '', thread: [{ id: 11, answers_to: 10, answers: { _extra: { text: 'wait for the release' } } }] }] } as never;
    Object.assign(ASK, { answered: true, answer_message_id: 11 });
    const host = await open();
    expect(q(host, '[data-ask-extra-answer]').textContent).toBe('wait for the release');
    expect(host.querySelector('[data-ask-extra-field]')).toBeNull();
    unmount(app!);
    huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'x', title: '', thread: [{ id: 11, answers_to: 10, answers: {} }] }] } as never;
    app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel' } });
    await settle();
    expect(host.querySelector('[data-ask-extra]')).toBeNull();
    Object.assign(ASK, { answered: false, answer_message_id: null });
  });
});

describe('the row and the thread', () => {
  const asked = { id: 10, item_id: 1, author: 'claude', kind: 'question', text: 'flat', answered: false, created_at: 1, seq: 1,
    context: 'seven rulings', questions: ['Close #54?', 'Which one?'], form: ASK.ask.questions };

  test('on the row a form ask is a lead line plus "N questions, answer": no context block, no numbered list, no text fallback', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const wall = { ...asked, text: 'seven rulings\n\n1. Close #54? (close / keep)\n2. Which one?', context: 'seven rulings\nthe long background' };
    app = mount(TaskManagerAsk, { target: host, props: { message: wall as never, folded: true } });
    await settle();
    expect(q(host, '[data-task-manager-ask-lead]').textContent).toBe('seven rulings');
    expect(q(host, '[data-ask-bubble="10"]').textContent).toContain('5 questions');
    expect(q(host, '[data-ask-open="10"]').textContent).toBe('answer');
    expect(host.querySelector('[data-task-manager-ask-list]')).toBeNull();
    expect(host.querySelector('[data-task-manager-ask-context]')).toBeNull();
    expect(host.textContent).not.toContain('the long background');
    expect(host.textContent).not.toContain('Close #54?');
    expect(askFold(wall as never)).toEqual({ foldable: false, text: '', context: '', shown: 0, limit: 0, more: false });
    unmount(app);
    app = mount(TaskManagerAsk, { target: host, props: { message: { ...wall, context: '' } as never, folded: true } });
    await settle();
    expect(host.querySelector('[data-task-manager-ask-lead]')).toBeNull();
    expect(q(host, '[data-ask-bubble="10"]').textContent).toContain('5 questions');
  });

  test('in the open thread an unanswered form ask IS the form; an answered one is its context and the muted bubble', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAsk, { target: host, props: { message: asked as never } });
    await settle();
    expect(q(host, '[data-ask-form="10"]').getAttribute('data-ask-mode')).toBe('inline');
    expect(q(host, '.hdq-context').textContent).toBe('seven rulings');
    expect(host.querySelector('[data-ask-bubble]')).toBeNull();
    unmount(app);
    app = mount(TaskManagerAsk, { target: host, props: { message: { ...asked, answered: true } as never } });
    await settle();
    expect(q(host, '[data-task-manager-ask-context]').textContent).toBe('seven rulings');
    expect(q(host, '[data-ask-bubble="10"]').textContent).toBe('answered 5 questions');
  });

  test('an answered form ask has left the row: the feed holds no answered question, Joe\'s answer never shows (section 40)', () => {
    const answer = { id: 11, item_id: 1, author: 'joe', kind: 'reply', text: 'answers to 5 questions:', answered: false, created_at: 4, seq: 4, answers_to: 10, answers: {} };
    const item = { id: 1, kind: '', created_by: 'claude', status: 'open', text: 't', created_seq: 0, thread: [{ ...asked, answered: true }, answer] } as never;
    expect(rowFeed(item)).toEqual([]);
  });

  test('a form is a comment target, not a number target; a reply never clears it from the row', () => {
    const item = { id: 1, kind: '', created_by: 'claude', status: 'question', text: 't', created_seq: 0,
      thread: [asked, { id: 12, item_id: 1, author: 'joe', kind: 'reply', text: 'wait, what about #1071?', answered: false, created_at: 5, seq: 5 }] } as never;
    expect(hasFormAsk(item)).toBe(true);
    expect(hasNumberedAsk(item)).toBe(false);
    expect(rowFeed(item).map((m) => m.id)).toEqual([10]);
    expect(askFold(asked as never).shown).toBe(0);
  });
});

describe('the panel and the answered view', () => {
  test('the panel is a dialog over the huddle that Escape and cancel close, keeping nothing', async () => {
    const closed = vi.fn();
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAskPanel, { target: host, props: { messageId: 10, close: closed } });
    await settle();
    const overlay = q(host, '.modal-overlay.hdq-modal');
    expect(overlay.getAttribute('role')).toBe('dialog');
    expect(overlay.getAttribute('aria-modal')).toBe('true');
    expect(q(host, '.hdq-label').textContent).toBe('answer');
    await click(q(host, '[data-ask-take-all]'));
    overlay.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(closed).toHaveBeenCalledTimes(1);
    await click(q(host, '[data-ask-close]'));
    expect(closed).toHaveBeenCalledTimes(2);
    expect(calls.some((c) => c.path.endsWith('/answer'))).toBe(false);
  });

  test('an answered form is read-only and shows the stored answers in words', async () => {
    const answers = { i54: { value: true, label: 'close', recommended: true }, ord: { order: ['m', 'k'], labels: ['M', 'K'], recommended: true }, why: { skipped: true } };
    huddle.groups = null;
    huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'issue rulings', title: '', thread: [{ id: 11, answers_to: 10, answers }] }] } as never;
    Object.assign(ASK, { answered: true, answer_message_id: 11 });
    const host = await open();
    expect(host.querySelector('[data-ask-submit]')).toBeNull();
    expect(q(host, '[data-ask-answer="i54"]').textContent).toContain('close');
    expect(q(host, '[data-ask-answer="ord"]').textContent).toContain('M > K');
    expect(host.querySelector('[data-ask-answer="why"]')).toBeNull();
    expect(host.querySelectorAll('input, textarea').length).toBe(0);
    Object.assign(ASK, { answered: false, answer_message_id: null });
  });
});

describe('buttons are the base button (#1710)', () => {
  test('the form is drawn with data-btn controls (pills, links, take all, send) and no hand-drawn button class', async () => {
    const host = await open();
    const btn = (sel: string): HTMLElement => q(host, sel);
    expect(btn('[data-ask-submit]').getAttribute('data-btn')).toBe('confirm');
    expect(btn('[data-ask-take-all]').hasAttribute('data-btn')).toBe(true);
    expect(btn('[data-ask-take="i54"]').getAttribute('data-btn')).toBe('secondary');
    expect(btn('[data-ask-add-note="i54"]').getAttribute('data-btn')).toBe('secondary');
    expect(btn('[data-ask-pick="yes"]').hasAttribute('data-btn')).toBe(true);
    expect(btn('[data-ask-keep="ord"]').getAttribute('data-btn')).toBe('secondary');
    expect(host.querySelector('.hdq-link, .hdq-tool, .hdq-seg, .hdq-opt--pill')).toBeNull();
  });
});
