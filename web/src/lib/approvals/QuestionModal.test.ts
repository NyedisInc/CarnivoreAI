/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

type Reply = { items: unknown[] };
let reply: Reply = { items: [] };
let refuse: string | null = null;
let failReads = 0;
const calls: { path: string; method: string; body: unknown }[] = [];

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {
    payload: unknown;
    constructor(message: string, readonly status: number, readonly code: string | null = null, payload: unknown = null) {
      super(message);
      this.payload = payload;
    }
  },
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body) : undefined });
    if (path.endsWith('/answer-all') && refuse) {
      const { ApiError } = await import('../../opscenter/api/auth.svelte');
      throw new ApiError('conflict', 409, null, { detail: { reason: refuse } });
    }
    if (path === '/approvals' && failReads > 0) {
      failReads -= 1;
      throw new Error('offline');
    }
    return path === '/approvals' ? reply : { answered: true };
  },
}));
vi.mock('../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ isLive: () => false, pushOrPoll: () => {}, onChange: () => () => {} }) }));

import QuestionModal from './QuestionModal.svelte';
import { approvals, inboxFocus, refreshApprovals } from './approvals.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  reply = { items: [] };
  refuse = null;
  failReads = 0;
  inboxFocus.session = null;
  calls.length = 0;
  approvals.items = [];
  approvals.status = 'idle';
});

const ASK = {
  id: 'dlg:ses_1:aa', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'pizza', kind: 'ask_user_question',
  question: 'Which color?', fingerprint: 'f1', rows: [], created_at: 100, questions_state: 'matched',
  questions_fingerprint: 'q'.repeat(64),
  questions: [
    { header: 'Color', question: 'Which color?', multi_select: false, options: [{ label: 'Red', description: 'warm' }, { label: 'Blue', description: 'cool' }] },
    { header: 'Toppings', question: 'Which toppings?', multi_select: true, options: [{ label: 'Cheese', description: 'melty' }, { label: 'Peppers', description: 'hot' }] },
    { header: 'Size', question: 'Which size?', multi_select: false, options: [{ label: 'Small', description: '' }, { label: 'Large', description: '' }] },
  ],
};
const MULTI_PREVIEW = {
  ...ASK, id: 'dlg:ses_3:cc', session_id: 'ses_3', session_name: 'previews', created_at: 300,
  questions: [{ header: 'Layout', question: 'Which layouts?', multi_select: true, options: [
    { label: 'Wide', description: '', preview: '[ wide ]' }, { label: 'Tall', description: '', preview: '[ tall ]' }] }],
};
const STARTUP = {
  id: 'dlg:ses_4:dd', source: 'dialog', host: 'local', session_id: 'ses_4', session_name: 'boot', kind: 'folder_trust',
  startup_kind: 'trust', question: 'Trust this folder?', fingerprint: 'f4', created_at: 400,
  rows: [{ label: 'Yes, I trust this folder', role: 'option' }, { label: 'No, exit', role: 'option' }],
};
const PERMISSION = {
  id: 'dlg:ses_2:bb', source: 'dialog', host: 'local', session_id: 'ses_2', session_name: 'other', kind: 'permission',
  question: 'Run ls?', fingerprint: 'f2', created_at: 200, plain_yes: 'Yes', plain_no: 'No', summary: 'bash: ls',
  rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
};

async function show(items: unknown[], closes: { n: number } = { n: 0 }): Promise<HTMLElement> {
  reply = { items };
  await refreshApprovals();
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(QuestionModal, { target, props: { onClose: () => { closes.n += 1; }, onJump: () => {} } }));
  flushSync();
  await tick();
  return target;
}

const q = (sel: string): HTMLElement => document.querySelector<HTMLElement>(sel)!;
const click = async (sel: string): Promise<void> => { q(sel).click(); await tick(); };
const posts = (): { path: string; method: string; body: unknown }[] => calls.filter((c) => c.method === 'POST');

describe('a multi-question ask', () => {
  test('is filled across its tabs and submitted once, in order', async () => {
    await show([ASK]);
    expect(document.querySelectorAll('.ak-tabs [role="tab"]').length).toBe(3);
    await click('[data-ask-option="Blue"]');
    await click('.ak-tabs [data-tab=\"1\"]');
    expect(q('[data-ask-question]').textContent).toBe('Which toppings?');
    await click('[data-ask-option="Cheese"]');
    await click('[data-ask-option="Peppers"]');
    await click('.ak-tabs [data-tab=\"2\"]');
    const other = q('[data-ask-other]') as HTMLInputElement;
    other.value = 'Medium';
    other.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    expect(posts()).toEqual([]);
    await click('[data-ask-submit]');
    expect(posts()).toEqual([{
      method: 'POST', path: '/sessions/ses_1/dialog/answer-all',
      body: { questions_fingerprint: 'q'.repeat(64), answers: [{ option: 'Blue' }, { options: ['Cheese', 'Peppers'] }, { other: 'Medium' }] },
    }]);
  });

  test('marks an unanswered question before the submit and sends it as an empty answer', async () => {
    await show([ASK]);
    await click('[data-ask-option="Red"]');
    expect(q('.ak-tabs [data-tab="1"] .oc-ptab__badge').textContent).toBe('unanswered');
    expect(q('[data-ask-left]').textContent).toBe('2 unanswered, left out');
    await click('.ak-tabs [data-tab=\"2\"]');
    await click('[data-ask-option="Large"]');
    await click('[data-ask-submit]');
    expect((posts()[0]!.body as { answers: unknown[] }).answers).toEqual([{ option: 'Red' }, {}, { option: 'Large' }]);
  });

  test('Enter goes next until the last question, which it submits; the default look follows', async () => {
    await show([ASK]);
    const enter = async (sel: string): Promise<void> => {
      q(sel).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
      await tick();
    };
    await click('[data-ask-option="Blue"]');
    expect(q('[data-ask-next]').getAttribute('data-btn')).toBe('confirm');
    expect(q('[data-ask-submit]').getAttribute('data-btn')).toBe('secondary');
    await enter('[data-ask-option="Blue"]');
    expect(q('[data-ask-question]').textContent).toBe('Which toppings?');
    await enter('[data-ask-option="Cheese"]');
    expect(q('[data-ask-panel]').dataset.askPanel).toBe('2');
    expect(posts()).toEqual([]);
    expect(q('[data-ask-submit]').getAttribute('data-btn')).toBe('confirm');
    await enter('[data-ask-other]');
    expect(posts().length).toBe(1);
  });

  test('cannot be submitted with nothing answered', async () => {
    await show([ASK]);
    expect((q('[data-ask-submit]') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('the modal', () => {
  test('shows a permission prompt with its real options and no approve or deny strip', async () => {
    await show([PERMISSION]);
    expect([...document.querySelectorAll<HTMLElement>('[data-ap-option]')].map((b) => b.title)).toEqual(['Yes', 'No']);
    expect(document.querySelector('[data-approval-approve]')).toBeNull();
  });

  test('pages across every session oldest first', async () => {
    await show([PERMISSION, ASK]);
    expect(q('[data-approval-position]').textContent).toBe('1 of 2');
    expect(document.querySelector('[data-ask-form]')).not.toBeNull();
    await click('[data-approval-pager] button:last-of-type');
    expect(q('[data-approval-position]').textContent).toBe('2 of 2');
    expect(document.querySelector('[data-approval-card="dlg:ses_2:bb"]')).not.toBeNull();
  });

  test('the answer buttons live in the pinned foot, outside the scrolling body, and the item pager sits in the title row', async () => {
    await show([PERMISSION, ASK]);
    const body = q('.modal-body');
    const footer = q('.modal-footer');
    expect(footer.querySelector('[data-ask-submit]')).not.toBeNull();
    expect(footer.querySelector('[data-ask-next]')).not.toBeNull();
    expect(body.querySelector('[data-ask-submit]')).toBeNull();
    expect(footer.querySelector('[data-approval-pager]')).toBeNull();
    expect(q('.text-prompt-modal__head').querySelector('[data-approval-pager]')).not.toBeNull();
    expect([...footer.querySelectorAll('button')].map((b) => b.textContent?.trim())).not.toContain('back');
    await click('[data-approval-pager] button:last-of-type');
    expect(q('.modal-footer').querySelector('[data-approval-deny-action], [data-ap-option]')).toBeNull();
    expect(q('.modal-footer').textContent).toContain('dismiss');
  });

  test('names the session as the sidebar does and never gives two buttons one label', async () => {
    await show([PERMISSION, { ...ASK, session_name: 'carnivore_pizza', tmux_session: 'carnivore_pizza' }]);
    expect(q('.ak-name').textContent).toBe('pizza');
    const labels = [...document.querySelectorAll('button')].map((b) => b.textContent?.trim()).filter((x) => x);
    expect(labels.filter((x) => x === 'next').length).toBe(1);
    expect(new Set(labels).size).toBe(labels.length);
  });

  test('closes itself when its last item is answered, and not before', async () => {
    const closes = { n: 0 };
    await show([ASK, PERMISSION], closes);
    reply = { items: [PERMISSION] };
    await refreshApprovals();
    await tick();
    expect(closes.n).toBe(0);
    expect(document.querySelector('[data-approval-card="dlg:ses_2:bb"]')).not.toBeNull();
    reply = { items: [] };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await refreshApprovals();
    await tick();
    expect(closes.n).toBe(0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(closes.n).toBe(1);
    vi.useRealTimers();
  });

  test('a settle read that fails is retried: it closes once a read finally shows nothing', async () => {
    const closes = { n: 0 };
    await show([ASK], closes);
    reply = { items: [] };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await refreshApprovals();
    await tick();
    failReads = 1;
    await vi.advanceTimersByTimeAsync(1600);
    expect(closes.n).toBe(0);
    await vi.advanceTimersByTimeAsync(700);
    expect(closes.n).toBe(1);
    vi.useRealTimers();
  });

  test('a settle read that fails then shows the ask again keeps the modal open (question 1 of N)', async () => {
    const closes = { n: 0 };
    await show([ASK], closes);
    reply = { items: [] };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await refreshApprovals();
    await tick();
    failReads = 1;
    await vi.advanceTimersByTimeAsync(1600);
    reply = { items: [ASK] };
    await vi.advanceTimersByTimeAsync(5000);
    await tick();
    expect(closes.n).toBe(0);
    expect(document.querySelector('[data-ask-form]')).not.toBeNull();
    vi.useRealTimers();
  });

  test('settle reads that keep failing close it once the retries are spent and the store holds nothing', async () => {
    const closes = { n: 0 };
    await show([ASK], closes);
    reply = { items: [] };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await refreshApprovals();
    await tick();
    failReads = Infinity;
    await vi.advanceTimersByTimeAsync(1600);
    expect(closes.n).toBe(0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(closes.n).toBe(1);
    vi.useRealTimers();
  });

  test('a second empty spell gets its own full settle, not the first spell\'s leftover timer (G2)', async () => {
    const closes = { n: 0 };
    await show([ASK], closes);
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    reply = { items: [] };
    await refreshApprovals();
    await tick();
    await vi.advanceTimersByTimeAsync(1000);
    reply = { items: [ASK] };
    await refreshApprovals();
    await tick();
    reply = { items: [] };
    await refreshApprovals();
    await tick();
    await vi.advanceTimersByTimeAsync(700);
    expect(closes.n).toBe(0);
    await vi.advanceTimersByTimeAsync(1200);
    expect(closes.n).toBe(1);
    vi.useRealTimers();
  });

  test('opened with nothing waiting it stays and says so', async () => {
    const closes = { n: 0 };
    await show([], closes);
    expect(q('[data-approval-empty]').textContent).toBe('nothing is waiting on you.');
    expect(closes.n).toBe(0);
  });
});

describe('the modal, more', () => {
  test('a notification click while it is open moves it to that session\'s item', async () => {
    await show([ASK, PERMISSION]);
    expect(document.querySelector('[data-ask-form]')).not.toBeNull();
    inboxFocus.session = 'ses_2';
    inboxFocus.seq += 1;
    await tick();
    expect(document.querySelector('[data-approval-card="dlg:ses_2:bb"]')).not.toBeNull();
    expect(document.querySelector('[data-ask-form]')).toBeNull();
  });

  test('a 409 drift shows its plain words on the form and the list is re-read', async () => {
    await show([ASK]);
    refuse = 'questions_changed';
    await click('[data-ask-option="Red"]');
    const reads = calls.filter((c) => c.path === '/approvals').length;
    await click('[data-ask-submit]');
    await vi.waitFor(() => expect(document.querySelector('[data-approval-notice]')).not.toBeNull());
    expect(q('[data-approval-notice]').textContent).toBe('the questions changed while you answered, look again.');
    expect(calls.filter((c) => c.path === '/approvals').length).toBe(reads + 1);
  });

  test('a raw server code the catalog lacks is never shown for the batch refusals', async () => {
    await show([ASK]);
    refuse = 'unsupported_question';
    await click('[data-ask-option="Red"]');
    await click('[data-ask-submit]');
    await vi.waitFor(() => expect(document.querySelector('[data-approval-notice]')).not.toBeNull());
    expect(q('[data-approval-notice]').textContent).toContain('multi select');
  });

  test('an answered multi-select with previews warns and holds the submit', async () => {
    await show([MULTI_PREVIEW]);
    expect((q('[data-ask-submit]') as HTMLButtonElement).disabled).toBe(true);
    await click('[data-ask-option="Wide"]');
    expect(q('[data-ask-unsupported]')).not.toBeNull();
    expect((q('[data-ask-submit]') as HTMLButtonElement).disabled).toBe(true);
    await click('[data-ask-option="Wide"]');
    expect(document.querySelector('[data-ask-unsupported]')).toBeNull();
  });

  test('a startup screen shows its rows and presses nothing until the owner clicks one', async () => {
    await show([STARTUP]);
    expect([...document.querySelectorAll('[data-ap-option]')].map((b) => b.textContent?.trim().replace(/\s+/g, ' ')))
      .toEqual(['yes, trust this folder', 'no, exit']);
    expect(posts()).toEqual([]);
    await click('[data-ap-option]');
    expect(posts().length).toBe(1);
  });
});
