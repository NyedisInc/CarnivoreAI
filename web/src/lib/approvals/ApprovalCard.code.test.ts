/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' }, initAuth: async () => {}, ApiError: class extends Error {},
  authFetch: async () => ({ items: [] }),
}));

import ApprovalCard from './ApprovalCard.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

const BODY = ' Bash command\n   ls\n   rm -rf build\n\n Do you want to proceed?\n ❯ 1. Yes\n   2. No';
const ITEM: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'api', kind: 'permission',
  question: 'Do you want to proceed?', body: BODY,
  rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
};

function draw(item: ApprovalItem): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {} } }));
  flushSync();
  return target;
}

describe('a code card', () => {
  test('our headline instead of claude\'s question, the command alone under details, no option rows in the text', () => {
    const card = draw(ITEM);
    const text = card.textContent ?? '';
    expect(text).not.toMatch(/Do you want to proceed\?/);
    expect(card.querySelector('[data-qc-headline]')?.textContent).toBe('api wants to run a 2 line script.');
    expect(card.querySelector('[data-qc-fact="risk"]')?.textContent).toBe('delete');
    const body = card.querySelector('[data-approval-body]');
    expect(body?.textContent).toBe('lsrm -rf build');
    expect(body?.textContent).not.toMatch(/Bash command|1\. Yes|2\. No/);
    expect(card.querySelectorAll('[data-ap-option]')).toHaveLength(2);
  });
  test('a risky line is tinted, a safe one is not', () => {
    const lines = draw(ITEM).querySelectorAll('.ap-line');
    expect(lines[0]?.classList.contains('ap-line--risk')).toBe(false);
    expect(lines[1]?.classList.contains('ap-line--risk')).toBe(true);
  });
  test('an item without code keeps its raw body, folded under details, with no open button beside it', () => {
    const card = draw({ ...ITEM, kind: 'plan', body: 'Plan\n  1. first step', rows: undefined });
    expect(card.querySelector('[data-approval-code]')).toBeNull();
    expect(card.querySelector('pre[data-approval-body]')?.textContent).toContain('1. first step');
    expect(card.querySelector<HTMLDetailsElement>('[data-qc-details]')?.open).toBe(false);
  });
  test('code shows open: the script is on screen beside the one-click approve, never only behind details', () => {
    const details = draw({ ...ITEM, plain_yes: 'Yes' }).querySelector<HTMLDetailsElement>('[data-qc-details]');
    expect(details?.open).toBe(true);
    expect(details?.querySelector('[data-approval-code]')).not.toBeNull();
  });
  test('a card with no raw text and no code draws no empty details row', () => {
    const question: ApprovalItem = { ...ITEM, kind: 'ask_user_question', question: 'Which one?', body: '', rows: [{ label: 'a', role: 'option' }] };
    const card = draw(question);
    expect(card.querySelector('.qc-more-row')).toBeNull();
    expect(draw(ITEM).querySelector('.qc-more-row')).not.toBeNull();
  });
});
