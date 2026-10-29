/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class extends Error {},
  authFetch: async () => ({ items: [] }),
}));

import ApprovalCard from './ApprovalCard.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
});

const BASH: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'api', kind: 'permission',
  question: 'Do you want to proceed?', fingerprint: 'f'.repeat(64), body: 'Bash command\n   touch rigfile',
  rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
  plain_yes: 'Yes', plain_no: 'No', summary: 'Bash command: touch rigfile',
};
const ASK: ApprovalItem = {
  id: 'dlg:ses_2:cd', source: 'dialog', host: 'local', session_id: 'ses_2', session_name: 'web', kind: 'ask_user_question',
  question: 'Which one?', fingerprint: 'e'.repeat(64), body: '',
  rows: [{ label: 'alpha', role: 'option', description: 'the first' }, { label: 'beta', role: 'option' }, { label: 'gamma', role: 'option' }],
};

function draw(item: ApprovalItem, props: Record<string, unknown> = {}): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {}, ...props } }));
  flushSync();
  return target;
}

describe('the bottom bar', () => {
  test('a permission prompt with code puts the options, approve, deny and the popout in one row, the open-session icon last', () => {
    const card = draw(BASH);
    const bars = card.querySelectorAll('[data-ap-bar]');
    expect(bars.length).toBe(1);
    const bar = bars[0] as HTMLElement;
    for (const sel of ['[data-ap-option]', '[data-approval-approve-go]', '[data-approval-deny]', '[data-approval-open]']) {
      expect(bar.querySelector(sel), sel).not.toBeNull();
    }
    const outside = [...card.querySelectorAll('.modal-btn')].filter((b) => !bar.contains(b));
    expect(outside).toEqual([]);
    expect(bar.lastElementChild?.hasAttribute('data-ap-jump')).toBe(true);
  });

  test('the open-session control is an icon-only button with an aria-label and title from the catalog', () => {
    const jump = draw(BASH).querySelector<HTMLButtonElement>('[data-ap-jump]');
    expect(jump).not.toBeNull();
    expect(jump?.getAttribute('aria-label')).toBe('open session');
    expect(jump?.getAttribute('title')).toBe('open session');
    expect(jump?.textContent?.trim()).toBe('');
    expect(jump?.querySelector('svg')).not.toBeNull();
  });

  test('it calls onJump with the item', () => {
    const jumped: string[] = [];
    draw(BASH, { onJump: (i: ApprovalItem) => jumped.push(i.id) }).querySelector<HTMLButtonElement>('[data-ap-jump]')?.click();
    expect(jumped).toEqual(['dlg:ses_1:ab']);
  });

  test('a question with many options keeps them all in the bar at one class, and an option description is a note above it', () => {
    const card = draw(ASK);
    const bar = card.querySelector('[data-ap-bar]') as HTMLElement;
    expect(bar.querySelectorAll('[data-ap-option]').length).toBe(3);
    expect(bar.classList.contains('ap-actions')).toBe(true);
    expect(bar.querySelector('.ap-opt-desc')).toBeNull();
    expect(card.querySelector('[data-ap-notes]')?.textContent).toContain('the first');
    expect(bar.lastElementChild?.hasAttribute('data-ap-jump')).toBe(true);
  });

  test('the question modal keeps its choices in the body and pins the foot bar', () => {
    const card = draw(ASK, { registerFoot: () => {} });
    expect(card.querySelector('[data-ap-bar] [data-ap-option]')).toBeNull();
    expect(card.querySelectorAll('.ap-picks [data-ap-option]').length).toBe(3);
  });
});
