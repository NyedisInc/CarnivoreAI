/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const posts: { path: string; body: unknown }[] = [];

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class extends Error {},
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'POST') {
      posts.push({ path, body: JSON.parse(init.body ?? '{}') });
      return { answered: true };
    }
    return { items: [] };
  },
}));

import ApprovalCard from '../approvals/ApprovalCard.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalItem } from '../approvals/approvals-model';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  posts.length = 0;
});

const BASH: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'api', kind: 'permission',
  question: 'Do you want to proceed?', fingerprint: 'f'.repeat(64), body: 'Bash command\nls -la\nsudo rm -rf build\ncat .env',
  rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
  plain_yes: 'Yes', plain_no: 'No', summary: 'Bash command: sudo rm -rf build',
};

function draw(item: ApprovalItem): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {} } }));
  flushSync();
  return target;
}

const open = (card: HTMLElement): void => {
  card.querySelector<HTMLElement>('[data-approval-open]')?.click();
  flushSync();
};

describe('the code review modal', () => {
  test('the open button shows only on a card with code', () => {
    expect(draw(BASH).querySelector('[data-approval-open]')).not.toBeNull();
    expect(draw({ ...BASH, id: 'x', kind: 'ask_user_question' }).querySelector('[data-approval-open]')).toBeNull();
    expect(draw({ ...BASH, id: 'y', body: '' }).querySelector('[data-approval-open]')).toBeNull();
  });

  test('it opens numbered lines with the risky ones marked, and the toggle filters', () => {
    open(draw(BASH));
    const lines = [...document.querySelectorAll<HTMLElement>('[data-code-review-lines] li')];
    expect(lines).toHaveLength(3);
    expect(lines.filter((l) => l.dataset.risk).map((l) => l.dataset.line)).toEqual(['2', '3']);
    document.querySelector<HTMLElement>('[data-code-review-toggle]')?.click();
    flushSync();
    expect([...document.querySelectorAll<HTMLElement>('[data-code-review-lines] li')].map((l) => l.dataset.line)).toEqual(['2', '3']);
  });

  test('approve here is the card answer, and the modal closes', async () => {
    open(draw(BASH));
    document.querySelector<HTMLElement>('[data-code-review-approve]')?.click();
    await tick();
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
    expect(posts.map((p) => p.body)).toEqual([expect.objectContaining({ choice: { plain: 'yes' } })]);
    expect(document.querySelector('[data-code-review]')).toBeNull();
  });

  test('deny sends no, and Escape closes without answering', async () => {
    open(draw(BASH));
    document.querySelector<HTMLElement>('[data-code-review-deny]')?.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(posts.map((p) => p.body)).toEqual([expect.objectContaining({ choice: { plain: 'no' } })]);
    posts.length = 0;
    open(draw({ ...BASH, id: 'z' }));
    document.querySelector('.modal-overlay')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(document.querySelector('[data-code-review]')).toBeNull();
    expect(posts).toEqual([]);
  });
});
