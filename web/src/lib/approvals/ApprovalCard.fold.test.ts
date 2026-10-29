/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' }, initAuth: async () => {}, ApiError: class extends Error {},
  authFetch: async (path: string) => (path === '/approvals' ? { items: [] } : []),
}));

import ApprovalCard from './ApprovalCard.svelte';
import DrawerQuestions from '../drawer-tabs/DrawerQuestions.svelte';
import { approvals } from './approvals.svelte';
import { setLocale, t } from '../i18n/index.svelte';
import Icon from '../../opscenter/ui/Icon.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  approvals.items = [];
});

const TRUST: ApprovalItem = {
  id: 'dlg:ses_9:fold', source: 'dialog', host: 'local', session_id: 'ses_9', session_name: 'omega', project: 'shelving',
  family: 'claude', kind: 'folder_trust', startup_kind: 'trust', fingerprint: 'a'.repeat(64),
  question: 'Quick safety check: Is this a project you created or one you trust?', body: 'Accessing workspace:\n/tmp/x',
  rows: [{ label: 'No, exit', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }],
};

function draw(item: ApprovalItem, props: Record<string, unknown> = { foldable: true, age: 'waiting 6m' }): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {}, ...props } }));
  flushSync();
  return target;
}

function foldButton(card: HTMLElement): HTMLButtonElement {
  return card.querySelector<HTMLButtonElement>('[data-qc-toggle]')!;
}

const ASK: ApprovalItem = {
  id: 'dlg:ses_7:q1', source: 'dialog', session_id: 'ses_7', session_name: 'nova', kind: 'ask_user_question',
  question: 'Which?', question_index: 1, question_total: 2, tabs: [{ title: 'a', answered: false }, { title: 'b', answered: false }],
  rows: [{ label: 'x', role: 'option' }],
};

describe('a foldable card', () => {
  test('starts open: facts, details, buttons and the chip are all drawn', () => {
    const card = draw({ ...TRUST, id: 'dlg:ses_9:one' });
    expect(foldButton(card).getAttribute('aria-expanded')).toBe('true');
    expect(card.querySelector('[data-qc-badge]')?.textContent).toBe('startup');
    expect(card.querySelector('[data-qc-age]')?.textContent).toBe('waiting 6m');
    expect(card.querySelector('[data-qc-facts]')).not.toBeNull();
    expect(card.querySelector('[data-qc-details]')).not.toBeNull();
    expect(card.querySelectorAll('[data-ap-option]')).toHaveLength(2);
    expect(card.querySelector('[data-qc-chip]')?.textContent).toBe('always waits for you');
  });

  test('a click on the head folds it to the headline; a second click opens it again', () => {
    const card = draw({ ...TRUST, id: 'dlg:ses_9:two' });
    foldButton(card).click();
    flushSync();
    expect(foldButton(card).getAttribute('aria-expanded')).toBe('false');
    expect(card.querySelector('[data-qc-headline]')?.textContent).toContain('trust this folder');
    expect(card.querySelector('[data-qc-facts]')).toBeNull();
    expect(card.querySelectorAll('[data-ap-option]')).toHaveLength(0);
    foldButton(card).click();
    flushSync();
    expect(foldButton(card).getAttribute('aria-expanded')).toBe('true');
    expect(card.querySelectorAll('[data-ap-option]')).toHaveLength(2);
  });

  test('a card folded by hand stays folded when it is drawn again (a re-read, a list change)', () => {
    const item = { ...TRUST, id: 'dlg:ses_9:three' };
    foldButton(draw(item)).click();
    flushSync();
    for (const app of apps.splice(0)) unmount(app);
    const again = draw(item);
    expect(foldButton(again).getAttribute('aria-expanded')).toBe('false');
    expect(again.querySelectorAll('[data-ap-option]')).toHaveLength(0);
  });

  test('the next question of an ask you folded arrives folded; a new prompt arrives open', () => {
    foldButton(draw(ASK)).click();
    flushSync();
    const next = draw({ ...ASK, id: 'dlg:ses_7:q2', question_index: 2 });
    expect(foldButton(next).getAttribute('aria-expanded')).toBe('false');
    expect(foldButton(draw({ ...TRUST, id: 'dlg:ses_9:new' })).getAttribute('aria-expanded')).toBe('true');
  });

  test('an ask nobody folded arrives open on its next question', () => {
    draw({ ...ASK, id: 'dlg:ses_6:q1', session_id: 'ses_6' });
    const next = draw({ ...ASK, id: 'dlg:ses_6:q2', session_id: 'ses_6', question_index: 2 });
    expect(foldButton(next).getAttribute('aria-expanded')).toBe('true');
  });

  test('the answers-review screen follows the ask before it; a later, different ask in the session arrives open', () => {
    const ask: ApprovalItem = { ...ASK, id: 'dlg:ses_8:q1', session_id: 'ses_8' };
    const review: ApprovalItem = {
      id: 'dlg:ses_8:rv', source: 'dialog', session_id: 'ses_8', session_name: 'nova', kind: 'ask_user_question',
      question: 'Ready to submit your answers?', rows: [{ label: 'Submit answers', role: 'option' }, { label: 'Cancel', role: 'option' }],
    };
    foldButton(draw(ask)).click();
    flushSync();
    expect(foldButton(draw(review)).getAttribute('aria-expanded')).toBe('false');
    const later = draw({ ...ask, id: 'dlg:ses_8:later', tabs: [{ title: 'c', answered: false }, { title: 'd', answered: false }] });
    expect(foldButton(later).getAttribute('aria-expanded')).toBe('true');
    expect(foldButton(draw({ ...review, id: 'dlg:ses_8:rv2' })).getAttribute('aria-expanded')).toBe('true');
  });

  test('the question modal\'s card is always open and has no fold toggle', () => {
    const card = draw({ ...TRUST, id: 'dlg:ses_9:modal' }, {});
    expect(card.querySelector('[data-qc-toggle]')).toBeNull();
    expect(card.querySelectorAll('[data-ap-option]')).toHaveLength(2);
  });
});

describe('the go-to-session button', () => {
  test('wears the pop-out icon (the arrow out of a square) and keeps its label and tooltip', () => {
    const card = draw({ ...TRUST, id: 'dlg:ses_9:jump' });
    const jump = card.querySelector<HTMLButtonElement>('[data-ap-jump]')!;
    expect(jump.getAttribute('title')).toBe(t('approvals.open_session'));
    expect(jump.getAttribute('aria-label')).toBe(t('approvals.open_session'));
    const reference = document.createElement('div');
    document.body.appendChild(reference);
    apps.push(mount(Icon, { target: reference, props: { name: 'external', size: 14 } }));
    flushSync();
    expect(jump.querySelector('svg')?.innerHTML).toBe(reference.querySelector('svg')!.innerHTML);
    const list = document.createElement('div');
    document.body.appendChild(list);
    apps.push(mount(Icon, { target: list, props: { name: 'list', size: 14 } }));
    flushSync();
    expect(jump.querySelector('svg')?.innerHTML).not.toBe(list.querySelector('svg')!.innerHTML);
  });
});

describe('the questions slide-out', () => {
  test('every cell is an open standard card; Enter on a card folded by hand opens it before any key can answer', async () => {
    approvals.items = [{ ...TRUST, id: 'dlg:ses_9:drawer', created_at: Date.now() / 1000 - 360 }];
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(DrawerQuestions, { target }));
    flushSync();
    const cell = target.querySelector<HTMLElement>('[data-dq-cell]')!;
    expect(cell.querySelector('[data-qc-toggle]')?.getAttribute('aria-expanded')).toBe('true');
    expect(cell.querySelector('[data-qc-age]')?.textContent).toBe('waiting 6m');
    cell.querySelector<HTMLButtonElement>('[data-qc-toggle]')!.click();
    flushSync();
    expect(cell.querySelector('[data-qc-toggle]')?.getAttribute('aria-expanded')).toBe('false');
    cell.focus();
    cell.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }));
    cell.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await tick();
    flushSync();
    expect(cell.querySelector('[data-qc-toggle]')?.getAttribute('aria-expanded')).toBe('true');
    expect(cell.querySelectorAll('[data-ap-option]')).toHaveLength(2);
  });
});
