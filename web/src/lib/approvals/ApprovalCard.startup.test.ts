/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const posts: { path: string; body: unknown }[] = [];

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'POST') {
      posts.push({ path, body: JSON.parse(init.body ?? '{}') });
      return { answered: true };
    }
    return { items: [] };
  },
}));

import ApprovalCard from './ApprovalCard.svelte';
import { setLocale, t } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  posts.length = 0;
});

const TRUST: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'brightfund',
  kind: 'folder_trust', startup_kind: 'trust', fingerprint: 'a'.repeat(64),
  question: 'Quick safety check: Is this a project you created or one you trust?',
  body: 'This folder pre-approves 4 tool permissions in .claude/settings.json',
  rows: [{ label: 'No, continue without these permissions', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }],
};

function draw(item: ApprovalItem): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {} } }));
  flushSync();
  return target;
}

describe('a decoded startup screen', () => {
  test('shows every option in screen order in plain words, its warning under details, the startup badge and no dismiss', () => {
    const card = draw(TRUST);
    const buttons = [...card.querySelectorAll<HTMLButtonElement>('[data-ap-option]')];
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(['no, go on without these permissions', 'yes, trust this folder']);
    expect(buttons.map((b) => b.title)).toEqual(['No, continue without these permissions', 'Yes, I trust this folder']);
    expect(card.querySelector('[data-qc-details] [data-approval-body]')?.textContent).toContain('pre-approves 4 tool permissions');
    expect(card.querySelector('[data-qc-badge]')?.textContent).toBe('startup');
    expect(card.querySelector('[data-qc-headline]')?.textContent).toBe('brightfund wants to know if you trust this folder before claude reads or runs anything in it.');
    expect(card.querySelector('[data-qc-fact="screen"]')?.textContent).toBe('folder trust');
    expect(card.textContent).not.toContain('Quick safety check');
    expect(card.textContent).not.toContain('dismiss');
    expect(card.querySelector('[data-approval-approve]')).toBeNull();
  });

  test('a click sends exactly that label with the drawn fingerprint', async () => {
    const card = draw(TRUST);
    card.querySelectorAll<HTMLButtonElement>('[data-ap-option]')[1]!.click();
    await tick();
    await tick();
    expect(posts).toEqual([{ path: '/sessions/ses_1/dialog/answer',
      body: { fingerprint: 'a'.repeat(64), choice: { option: 'Yes, I trust this folder' } } }]);
  });

  test('a row that quits the agent is the danger button, the startup yes confirms', () => {
    const card = draw({ ...TRUST, kind: 'other', startup_kind: 'bypass_permissions',
      rows: [{ label: 'No, exit', role: 'option' }, { label: 'Yes, I accept', role: 'option' }] });
    const [exit, accept] = [...card.querySelectorAll<HTMLButtonElement>('[data-ap-option]')];
    expect(exit!.classList.contains('modal-btn-danger')).toBe(true);
    expect(accept!.classList.contains('modal-btn-confirm')).toBe(true);
    expect(card.querySelector('[data-qc-fact="if_no"]')?.textContent).toBe('claude exits and the session stops');
  });

  test('an ordinary dialog keeps its dismiss', () => {
    const card = draw({ ...TRUST, kind: 'permission', startup_kind: null });
    expect(card.textContent).toContain('dismiss');
  });
});

describe('a startup screen whose options did not read', () => {
  test.each([
    ['oauth_login', 'browser'], ['resume_picker', 'picker'], ['trust', 'unread'],
  ])('a %s card has no buttons and says why (%s)', (kind, reason) => {
    const card = draw({ id: 'sp:ses_1:1', source: 'startup_prompt', session_id: 'ses_1', kind, body: 'screen', rows: [] });
    expect(card.querySelectorAll('[data-ap-option]').length).toBe(0);
    expect(card.querySelector('[data-qc-fact="why_none"]')?.textContent).toBe(t(`approvals.card.v.readonly_${reason}`));
    expect(card.querySelector('[data-qc-chip]')?.textContent).toBe('read only');
  });
});
