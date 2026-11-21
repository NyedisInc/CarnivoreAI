/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  state: 'asleep' as string,
  scope: 'project' as string,
  commits: [] as unknown[],
  reason: null as string | null,
  conversations: [] as unknown[],
  posts: [] as Array<{ path: string; body: unknown }>,
  entries: [] as unknown[],
}));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method === 'POST') {
        server.posts.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
        return {};
      }
      if (path === '/swarm/agents/7') {
        return { id: 7, display_name: 'Rook', rank: 'feature', state: server.state, thread_key: 'agent:7', session_id: null, tmux_session: null, memory_scope: server.scope };
      }
      if (path === '/swarm/agents/7/checkpoints') return { commits: server.commits, reason: server.reason };
      if (path === '/swarm/agents/7/conversations') return server.conversations;
      if (path.startsWith('/swarm/agents/7/conversation?')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import { cardVariant, checkpointBlock, chatSlotId, menuHasRewind, rewindBlock } from './chat-model';

// jsdom has no popover API; the one item menu shows its levels through it (#2613).
const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

let app: object | null = null;

const COMMITS = [
  { sha: 'a'.repeat(40), at: '2026-10-05T14:02:00-04:00', subject: 'swarm: rook memory', kind: 'memory' },
  { sha: 'b'.repeat(40), at: '2026-10-04T10:00:00-04:00', subject: 'swarm: rook flipped back to a task agent', kind: 'flip_back' },
];
const CONVERSATIONS = [
  { wake_id: 2, conversation_uuid: '11111111-1111-4111-8111-111111111111', started_at: '2026-10-05T11:00:00-04:00', reason: 'manual', authority: 'data', transcript_present: true },
  { wake_id: 1, conversation_uuid: '22222222-2222-4222-8222-222222222222', started_at: '2026-10-04T11:00:00-04:00', reason: 'spawn', authority: 'data', transcript_present: false },
];

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

async function openPicker(host: HTMLElement): Promise<void> {
  host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
  flushSync();
  const item = document.querySelector('[data-node="rewind"]') as HTMLButtonElement;
  expect(item).toBeTruthy();
  item.click();
  await vi.waitFor(() => expect(host.querySelector('[data-rewind-sha]')).not.toBeNull());
}

beforeEach(() => {
  Object.assign(server, { state: 'asleep', scope: 'project', commits: COMMITS, reason: null, conversations: CONVERSATIONS, posts: [], entries: [] });
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
  registerCplugWidgets(huddleCplug);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('the pure rules', () => {
  test('the menu offers rewind to every unfinished agent, and a body that is up must sleep first', () => {
    expect(menuHasRewind('asleep')).toBe(true);
    expect(menuHasRewind('awake')).toBe(true);
    expect(menuHasRewind('torn_down')).toBe(false);
    expect(menuHasRewind(null)).toBe(false);
    expect(rewindBlock('asleep')).toBeNull();
    expect(rewindBlock('awake')).toMatch(/block_awake$/);
    expect(checkpointBlock('flip_back')).toMatch(/block_flip_back$/);
    expect(checkpointBlock('memory')).toBeNull();
  });

  test('a promotion receipt is chosen by its swarm_ref, ahead of the kind', () => {
    expect(cardVariant({ swarm_ref: 'promotion:4', kind: 'question' } as never)).toBe('promotion');
    expect(cardVariant({ swarm_ref: 'question:4', kind: 'question' } as never)).toBe('ask');
    expect(cardVariant({ swarm_ref: null, kind: 'question' } as never)).toBeNull();
  });
});

describe('the rewind picker', () => {
  test('lists both, rewinds with the sha, and refuses the flip-back commit and a missing transcript', async () => {
    const host = await mountChat();
    await openPicker(host);
    const rows = [...host.querySelectorAll<HTMLElement>('[data-rewind-sha]')];
    expect(rows.map((r) => r.dataset.rewindSha)).toEqual(['a'.repeat(40), 'b'.repeat(40)]);
    const keys = rows.map((r) => r.querySelector('button') as HTMLButtonElement);
    expect(keys[0]!.disabled).toBe(false);
    expect(keys[1]!.disabled).toBe(true);
    expect(keys[1]!.title).toContain('removed the memory folder');
    const convs = [...host.querySelectorAll<HTMLElement>('[data-rewind-conversation]')].map((r) => r.querySelector('button') as HTMLButtonElement);
    expect(convs.map((b) => b.disabled)).toEqual([false, true]);
    expect(convs[1]!.title).toContain('not on disk');

    keys[0]!.click();
    await vi.waitFor(() => expect(server.posts).toEqual([{ path: '/swarm/agents/7/rewind', body: { sha: 'a'.repeat(40) } }]));
    await vi.waitFor(() => expect(host.querySelector('[data-chat-rewind]')).toBeNull());
  });

  test('resume posts the conversation uuid', async () => {
    const host = await mountChat();
    await openPicker(host);
    (host.querySelector('[data-rewind-conversation] button') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(server.posts).toEqual([
      { path: '/swarm/agents/7/wake', body: { conversation_uuid: '11111111-1111-4111-8111-111111111111' } },
    ]));
  });

  test('an awake agent disables every row with the reason; local memory shows its reason instead of a list', async () => {
    server.state = 'awake';
    server.commits = [];
    server.reason = 'its memory is local to this computer and is not in git, so there is nothing to rewind';
    const host = await mountChat();
    host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    (document.querySelector('[data-node="rewind"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(host.querySelector('[data-rewind-conversation]')).not.toBeNull());
    expect(host.textContent).toContain('put the agent to sleep first');
    expect(host.textContent).toContain('is not in git');
    expect([...host.querySelectorAll<HTMLButtonElement>('[data-rewind-conversation] button')].every((b) => b.disabled)).toBe(true);
  });
});

describe('the promotion receipt card', () => {
  test('renders keep and flip back, not the question card; keep approves', async () => {
    server.entries = [{
      kind: 'card', id: 'item:9', at: 1, card: 'question',
      item: { id: 9, list: 'agent:7', text: 'Rook is now a feature agent', title: 'promoted: Rook', note: '', position: 1, created_by: 'claude', state: 'open',
              kind: 'question', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [], swarm_ref: 'promotion:3' },
    }];
    const host = await mountChat();
    const cardEl = host.querySelector('[data-chat-card]') as HTMLElement;
    expect(cardEl.dataset.chatCard).toBe('promotion');
    expect(cardEl.textContent).not.toContain('a question for you');
    const labels = [...cardEl.querySelectorAll('[data-chat-receipt] button')].map((b) => b.textContent);
    expect(labels).toEqual(['flip back', 'keep']);
  });
});
