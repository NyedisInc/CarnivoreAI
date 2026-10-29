/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

let reply: { items: unknown[] } = { items: [] };
const calls: { path: string; method: string }[] = [];

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string, init?: { method?: string }) => {
    calls.push({ path, method: init?.method ?? 'GET' });
    return path === '/approvals' ? reply : null;
  },
}));

import QuestionModal from './QuestionModal.svelte';
import { approvals, refreshApprovals } from './approvals.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  reply = { items: [] };
  calls.length = 0;
  approvals.items = [];
  approvals.status = 'idle';
});

const ITEM = {
  id: 'sp:ses_1:abcd', source: 'startup_prompt', host: 'local', session_id: 'ses_1', session_name: 'planner',
  project: 'Garden Planner', kind: 'mcp_server', question: '', rows: [], options: [],
  body: 'New MCP server found in this project: probe-echo\n  Enter to confirm · Esc to cancel',
};

describe('the startup-prompt card', () => {
  test('appears read-only, opens the session on click, and clears when the screen is gone', async () => {
    const jumped: ApprovalItem[] = [];
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(QuestionModal, { target, props: { onClose: () => {}, onJump: (item: ApprovalItem) => jumped.push(item) } }));
    flushSync();

    reply = { items: [ITEM] };
    await refreshApprovals();
    await tick();
    const card = target.querySelector<HTMLElement>('[data-approval-card="sp:ses_1:abcd"]');
    expect(card).not.toBeNull();
    expect(card?.dataset.source).toBe('startup_prompt');
    expect(card?.querySelector('[data-qc-headline]')?.textContent).toBe('planner is stopped on a startup screen, so there are no buttons here.');
    expect(card?.querySelector('[data-qc-fact="screen"]')?.textContent).toBe('mcp server');
    expect(card?.querySelector('[data-qc-details] [data-approval-body]')?.textContent).toContain('probe-echo');
    expect(target.querySelectorAll('[data-approval-card] .modal-btn:not([data-ap-jump])').length).toBe(0);

    calls.length = 0;
    target.querySelector<HTMLButtonElement>('[data-ap-jump]')?.click();
    expect(jumped.map((i) => i.session_id)).toEqual(['ses_1']);
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([]);

    reply = { items: [] };
    await refreshApprovals();
    await tick();
    expect(target.querySelector('[data-approval-card]')).toBeNull();
  });

  test('an unknown kind reads as a startup screen, not a raw key', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(QuestionModal, { target, props: { onClose: () => {}, onJump: () => {} } }));
    reply = { items: [{ ...ITEM, id: 'sp:ses_2:x', kind: 'something_new' }] };
    await refreshApprovals();
    await tick();
    const text = target.querySelector('[data-approval-card="sp:ses_2:x"]')?.textContent ?? '';
    expect(text).toContain('startup screen');
    expect(text).not.toContain('approvals.startup.kind');
  });
});
