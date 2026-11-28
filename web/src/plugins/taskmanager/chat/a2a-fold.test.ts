/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({ entries: [] as unknown[], posts: [] as { path: string; body: unknown }[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method === 'POST') {
        server.posts.push({ path, body: JSON.parse(String(init.body ?? '{}')) });
        return { outcome: 'delivered' };
      }
      if (path === '/swarm/agents/7' && method === 'GET') {
        return { id: 7, display_name: 'Loki', rank: 'project', state: 'awake', thread_key: '12', session_id: null, tmux_session: null };
      }
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import { accountChip } from '../../../lib/drawer-hud/account-menu.svelte';
import ChatWidget from './ChatWidget.svelte';
import { chatSlotId } from './chat-model';

let app: object | null = null;
const own = [{ kind: 'agent', name: 'Loki', agent_id: 7 }];
const you = [{ kind: 'owner', name: 'alex', agent_id: null }];
const outside = [{ kind: 'agent', name: 'Fenrir', agent_id: 9 }];
const question = {
  kind: 'card', id: 'item:41', at: 5, card: 'question', author_path: outside,
  item: { id: 41, list: 'agent:7', text: 'which port?', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [] },
};

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  server.entries = [];
  server.posts = [];
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
  accountChip.identity = null;
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

const order = 'Owner order (Alex, via Acme company agent): rename the NHI flow page.\n\nDo:\n1. copy it in both buckets';
const traffic = {
  kind: 'traffic', id: 'xt:5', at: 8, direction: 'out', peer: 'Cobalt', peer_session_uuid: 'u-argent', text: order,
  summary: 'Owner order (Alex, via Acme company agent): rename the NHI flow page.', thread: 't-1', in_reply_to: null,
  receipt: { status: 'delivered' }, author_path: own,
};
const ownerSays = { kind: 'owner', id: 'msg:1', at: 6, text: 'rename the nhi page\nand reply with both urls', author_path: you };

describe('agent-to-agent messages fold to one line', () => {
  test('a crosstalk entry shows the server summary in the hairline frame, opens in full and folds again; the owner stays full', async () => {
    server.entries = [ownerSays, traffic];
    const host = await mountChat();
    const block = host.querySelector('[data-traffic-id="xt:5"]') as HTMLElement;
    expect(block.classList.contains('hdx--bare')).toBe(true);
    expect(block.getAttribute('data-traffic-open')).toBe('false');
    expect(block.querySelector('[data-traffic-summary]')?.textContent).toBe(traffic.summary);
    expect(block.textContent).not.toContain('copy it in both buckets');
    expect(block.querySelector('[data-chat-recipient]')?.textContent).toContain('Cobalt');
    const toggle = block.querySelector('[data-traffic-toggle]') as HTMLButtonElement;
    expect(toggle.textContent?.trim()).toBe('show full');
    toggle.click();
    flushSync();
    expect(block.getAttribute('data-traffic-open')).toBe('true');
    expect(block.querySelector('[data-traffic-summary]')).toBeNull();
    expect(block.textContent).toContain('copy it in both buckets');
    expect(toggle.textContent?.trim()).toBe('show less');
    toggle.click();
    flushSync();
    expect(block.querySelector('[data-traffic-summary]')).not.toBeNull();
    const owner = host.querySelector('[data-entry-id="msg:1"]') as HTMLElement;
    expect(owner.textContent).toContain('and reply with both urls');
    expect(owner.querySelector('[data-traffic-toggle]')).toBeNull();
  });

  test('with no server summary the block opens in full and offers no toggle (the client never makes one up)', async () => {
    server.entries = [{ ...traffic, summary: '' }];
    const host = await mountChat();
    const block = host.querySelector('[data-traffic-id="xt:5"]') as HTMLElement;
    expect(block.textContent).toContain('copy it in both buckets');
    expect(block.querySelector('[data-traffic-toggle], [data-traffic-summary]')).toBeNull();
  });
});

describe("the owner's square", () => {
  test('a signed-in member gets the profile identicon; otherwise the initials, never "you"', async () => {
    server.entries = [ownerSays];
    let host = await mountChat();
    let av = host.querySelector('[data-chat-owner-av]') as HTMLElement;
    expect(av.getAttribute('data-chat-owner-av')).toBe('initials');
    expect(av.textContent?.trim()).toBe('A');
    expect(av.querySelector('svg')).toBeNull();
    unmount(app!, { outro: false });
    app = null;
    accountChip.identity = { kind: 'member', name: 'example-owner', provider: 'github' };
    host = await mountChat();
    av = host.querySelector('[data-chat-owner-av]') as HTMLElement;
    expect(av.getAttribute('data-chat-owner-av')).toBe('icon');
    expect(av.querySelector('svg')).not.toBeNull();
    expect(av.textContent?.trim().toLowerCase()).not.toBe('you');
  });
});

describe('a question between agents (#2599)', () => {
  test('the question and the answer draw as two plain messages by their authors, with no receipt row', async () => {
    server.entries = [
      { kind: 'agent', id: 'q:3:ask:9', at: 10, text: 'which **port** for studio?', author_path: outside },
      { kind: 'agent', id: 'q:3:answer', at: 11, text: 'use 8000', author_path: own },
    ];
    const host = await mountChat();
    const asked = host.querySelector('[data-entry-id="q:3:ask:9"]') as HTMLElement;
    const answer = host.querySelector('[data-entry-id="q:3:answer"]') as HTMLElement;
    expect(asked.getAttribute('data-chat-entry')).toBe('agent');
    expect(asked.querySelector('.hdc-text strong')?.textContent).toBe('port');
    expect(asked.textContent).toContain('Fenrir');
    expect(answer.getAttribute('data-chat-entry')).toBe('agent');
    expect(answer.querySelector('.hdc-text')?.textContent?.trim()).toBe('use 8000');
    expect(host.querySelector('[data-chat-receipt], [data-receipt-fact]')).toBeNull();
    expect(host.textContent).not.toMatch(/receipt|make craft|kill fact|your message/i);
  });
});
