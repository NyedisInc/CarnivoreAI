/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const posts: { path: string; body: unknown }[] = [];
let reads = 0;
let refuse = false;

vi.mock('../../opscenter/api/auth.svelte', () => {
  class ApiError extends Error {
    payload: unknown;
    constructor(message: string, payload: unknown) {
      super(message);
      this.payload = payload;
    }
  }
  return {
    auth: { state: 'signed-in' },
    initAuth: async () => {},
    ApiError,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'POST') {
        posts.push({ path, body: JSON.parse(init.body ?? '{}') });
        if (refuse) throw new ApiError('409', { detail: { reason: 'dialog_changed' } });
        return { answered: true };
      }
      if (path === '/approvals') reads += 1;
      return { items: refuse ? [{ ...BASH, id: 'dlg:ses_1:cd' }] : [] };
    },
  };
});

import ApprovalCard from './ApprovalCard.svelte';
import { approvals } from './approvals.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  posts.length = 0;
  reads = 0;
  refuse = false;
  approvals.notices = {};
});

const BASH: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'api', kind: 'permission',
  question: 'Do you want to proceed?', fingerprint: 'f'.repeat(64), body: 'Bash command\n   touch rigfile',
  rows: [{ label: 'Yes', role: 'option' }, { label: "Yes, and don't ask again", role: 'option' }, { label: 'No', role: 'option' }],
  plain_yes: 'Yes', plain_no: 'No', summary: 'Bash command: touch rigfile',
};

function draw(item: ApprovalItem): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {} } }));
  flushSync();
  return target;
}

describe('the approve strip', () => {
  test('a permission prompt with a plain yes says what it approves once, as the command fact, then approve and deny', () => {
    const card = draw(BASH);
    expect(card.querySelector('[data-qc-fact="command"]')?.textContent).toBe('touch rigfile');
    expect(card.querySelector('[data-ap-bar]')?.textContent).not.toContain('touch rigfile');
    expect(card.querySelector('[data-approval-approve-go]')?.classList.contains('modal-btn-confirm')).toBe(true);
    expect(card.querySelector('[data-approval-deny]')?.classList.contains('modal-btn-secondary')).toBe(true);
  });

  test.each([
    ['a question', { kind: 'ask_user_question', plain_yes: null }],
    ['a plan', { kind: 'plan_approval', plain_yes: null }],
    ['folder trust', { kind: 'folder_trust', plain_yes: null }],
    ['an older server that sent no plain yes', { plain_yes: undefined }],
  ])('%s gets no approve strip', (_name, patch) => {
    const card = draw({ ...BASH, ...patch } as ApprovalItem);
    expect(card.querySelector('[data-approval-approve]')).toBeNull();
  });

  test('approve sends plain yes with the fingerprint the card was drawn from', async () => {
    const card = draw(BASH);
    card.querySelector<HTMLButtonElement>('[data-approval-approve-go]')!.click();
    await tick();
    await tick();
    expect(posts).toEqual([{ path: '/sessions/ses_1/dialog/answer', body: { fingerprint: 'f'.repeat(64), choice: { plain: 'yes' } } }]);
  });

  test('a 409 says the prompt changed on that session\'s card and re-reads the list', async () => {
    refuse = true;
    const card = draw(BASH);
    card.querySelector<HTMLButtonElement>('[data-approval-deny]')!.click();
    await vi.waitFor(() => expect(reads).toBeGreaterThan(0));
    expect(posts[0]?.body).toEqual({ fingerprint: 'f'.repeat(64), choice: { plain: 'no' } });
    expect(approvals.notices['dialog:ses_1']).toBe('the prompt changed, look again.');
  });
});
