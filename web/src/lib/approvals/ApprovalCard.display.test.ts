/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ reply: { items: [] as unknown[] }, posts: [] as { path: string; body: unknown }[], refuse: false }));

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
        server.posts.push({ path, body: init.body ? JSON.parse(init.body) : null });
        if (server.refuse) throw new ApiError('type the exact name shown on the card to confirm', { detail: 'mismatch' });
        return { status: 'approved' };
      }
      return path === '/approvals' ? server.reply : null;
    },
  };
});

import ApprovalCard from './ApprovalCard.svelte';
import { approvals, refreshApprovals } from './approvals.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const PURGE = {
  id: 'act_p', source: 'agent_action', session_id: 'u1', kind: 'session_purge', action: 'session_purge',
  caller: 'carnivore_ops', summary: 'PURGE asleep session trader for good. Plan fp9.', confirm_text: 'trader',
  display: {
    verb: 'purge', object: 'session', name: 'trader', tone: 'danger',
    consequences: [{ key: 'purge_gone', params: {} }, { key: 'cannot_undo', params: {} }],
    detail: [{ key: 'fingerprint', value: 'fp9' }, { key: 'summary', value: 'PURGE asleep session trader for good. Plan fp9.' }],
  },
};

const MOVE = {
  id: 'act_m', source: 'agent_action', session_id: '', kind: 'project_move', action: 'project_move',
  caller: 'carnivore_ops', summary: 'move project "trader" to "/Users/x/Development/Org/Personal/trader"',
  display: {
    verb: 'move', object: 'project', name: 'trader', tone: 'confirm',
    consequences: [{ key: 'moves_to', params: { to: '~/Development/Org/Personal/trader' } }],
    detail: [{ key: 'new_root', value: '/Users/x/Development/Org/Personal/trader' }],
  },
};

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  server.reply = { items: [] };
  server.posts.length = 0;
  server.refuse = false;
  approvals.items = [];
  approvals.notices = {};
});

async function pane(items: unknown[]): Promise<HTMLElement> {
  server.reply = { items };
  const target = document.createElement('div');
  document.body.appendChild(target);
  await refreshApprovals();
  for (const item of approvals.items) apps.push(mount(ApprovalCard, { target, props: { item, onJump: () => {} } as never }));
  await tick();
  flushSync();
  return target;
}

function type(host: HTMLElement, text: string): void {
  const input = host.querySelector<HTMLInputElement>('[data-approval-confirm-input]')!;
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
}

describe('the scannable approval card on the approvals pane', () => {
  test('the standard card: the headline says who asks to do the verb and object on the name, the consequences are facts, the detail full', async () => {
    const host = await pane([MOVE]);
    expect(host.querySelector('[data-qc-badge]')?.textContent).toBe('agent');
    expect(host.querySelector('[data-qc-headline]')?.textContent).toMatch(/asks to move project trader\.$/);
    expect(host.querySelector('[data-qc-fact="effect"]')?.textContent).toContain('moves to ~/Development/Org/Personal/trader');
    expect(host.querySelector('[data-qc-chip]')?.textContent).toBe('mcp write');
    expect(host.querySelector('[data-approval-detail]')?.textContent).toContain('/Users/x/Development/Org/Personal/trader');
    const approve = host.querySelector<HTMLButtonElement>('[data-approval-approve-action]')!;
    expect(approve.getAttribute('data-btn')).toBe('confirm');
    expect(host.querySelector('[data-approval-deny-action]')?.getAttribute('data-btn')).toBe('secondary');
  });

  test('the visible words are plain: no terminal-multiplexer, record or re-point talk above the fold', async () => {
    const REMOVE = {
      id: 'act_r', source: 'agent_action', session_id: '', kind: 'project_archive', action: 'project_archive',
      caller: 'carnivore_ops', summary: 'archive project "trader"',
      display: {
        verb: 'archive', object: 'project', name: 'trader', tone: 'confirm',
        consequences: [{ key: 'list_only', params: {} }, { key: 'folder_untouched', params: {} }],
        detail: [],
      },
    };
    const host = await pane([PURGE, REMOVE]);
    const text = host.querySelector('[data-approval-card="act_p"] [data-qc-facts]')?.textContent ?? '';
    expect(text).toContain('everything carnivore and claude kept for it is deleted, transcripts included');
    expect(host.querySelector('[data-approval-card="act_r"] [data-qc-headline]')?.textContent).toMatch(/asks to archive project trader\.$/);
    expect(host.textContent).not.toMatch(/tmux|re-point|database rows/);
  });

  test('no typed ask renders anywhere when nothing asks for typed words', async () => {
    const host = await pane([MOVE]);
    expect(host.querySelector('[data-approval-confirm]')).toBeNull();
    expect(host.textContent).not.toContain('exactly to confirm');
    expect(host.querySelector<HTMLButtonElement>('[data-approval-approve-action]')!.disabled).toBe(false);
  });

  test('a purge shows the typed box; approve stays off until the exact name, then sends it', async () => {
    const host = await pane([PURGE]);
    const card = host.querySelector('[data-approval-card="act_p"]')!;
    expect(card.querySelector('[data-approval-confirm="act_p"]')?.textContent).toContain('type trader exactly to confirm');
    const approve = card.querySelector<HTMLButtonElement>('[data-approval-approve-action]')!;
    expect(approve.getAttribute('data-btn')).toBe('danger');
    expect(approve.disabled).toBe(true);
    type(host, 'Trader');
    expect(approve.disabled).toBe(true);
    type(host, 'trader');
    expect(approve.disabled).toBe(false);
    approve.click();
    await vi.waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0]).toEqual({ path: '/agent-actions/act_p/approve', body: { typed: 'trader' } });
  });

  test('a refusal shows inside its own card and leaves with the card', async () => {
    server.refuse = true;
    const host = await pane([PURGE, MOVE]);
    type(host, 'trader');
    host.querySelector<HTMLButtonElement>('[data-approval-card="act_p"] [data-approval-approve-action]')!.click();
    await vi.waitFor(() => expect(host.querySelector('[data-approval-card="act_p"] [data-approval-notice]')).not.toBeNull());
    expect(host.querySelector('[data-approval-card="act_m"] [data-approval-notice]')).toBeNull();
    server.reply = { items: [MOVE] };
    await refreshApprovals();
    await tick();
    flushSync();
    expect(host.querySelector('[data-approval-notice]')).toBeNull();
    expect(host.textContent).not.toContain('type the exact name');
  });
});
