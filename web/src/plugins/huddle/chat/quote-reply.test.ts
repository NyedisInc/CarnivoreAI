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
import ChatWidget from './ChatWidget.svelte';
import { chatSlotId } from './chat-model';

let app: object | null = null;
const own = [{ kind: 'agent', name: 'Loki', agent_id: 7 }];
const you = [{ kind: 'owner', name: 'alex', agent_id: null }];
const outside = [{ kind: 'agent', name: 'Fenrir', agent_id: 9 }];
const question = {
  kind: 'card', id: 'item:41', at: 5, card: 'question', author_path: outside, waits_on_owner: true,
  item: { id: 41, list: 'agent:7', text: 'which port?', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [] },
};

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

async function sendQuoted(root: HTMLElement, entryId: string, words: string): Promise<void> {
  (root.querySelector(`[data-chat-quote="${entryId}"]`) as HTMLButtonElement).click();
  flushSync();
  const box = root.querySelector('.hdc-input') as HTMLTextAreaElement;
  box.value = words;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  (root.querySelector('.hdc-compose') as HTMLFormElement).dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await vi.waitFor(() => expect(server.posts.length).toBe(1));
}

beforeEach(() => {
  server.entries = [];
  server.posts = [];
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

describe('quote-reply', () => {
  test('a chat card has no reply box of its own; every message has one quote key', async () => {
    server.entries = [question, { kind: 'agent', id: 'msg:2', at: 6, text: 'done', author_path: own }];
    const root = await mountChat();
    expect(root.querySelector('.hdr, [data-huddle-reply]')).toBeNull();
    expect(root.querySelectorAll('[data-chat-quote]').length).toBe(2);
  });

  test('quoting an open question keeps its item id: the reply is the huddle reply on that item', async () => {
    server.entries = [question];
    const root = await mountChat();
    await sendQuoted(root, 'item:41', '8080');
    expect(server.posts[0]).toEqual({ path: '/cplugs/huddle/items/41/messages', body: { text: '8080', client_id: expect.any(String) } });
  });

  test('quoting a plain message sends an order carrying the quoted words', async () => {
    server.entries = [{ kind: 'agent', id: 'msg:2', at: 6, text: 'the build is green', author_path: own }];
    const root = await mountChat();
    await sendQuoted(root, 'msg:2', 'ship it');
    expect(server.posts[0]).toEqual({ path: '/swarm/agents/7/messages', body: { text: '> the build is green\n\nship it' } });
  });
});

describe('the name line', () => {
  test('own and owner messages draw no name line, the time under the node; an outside agent keeps its name', async () => {
    server.entries = [
      { kind: 'agent', id: 'msg:1', at: 4, text: 'mine', author_path: own },
      { kind: 'owner', id: 'msg:2', at: 5, text: 'go', author_path: you },
      { kind: 'traffic', id: 'xt:3', at: 6, direction: 'in', peer: 'Fenrir', text: 'hello', thread: 't', in_reply_to: null, receipt: null, author_path: outside },
    ];
    const root = await mountChat();
    const row = (id: string) => root.querySelector(`[data-entry-id="${id}"]`) as HTMLElement;
    for (const id of ['msg:1', 'msg:2']) {
      expect(row(id).querySelector('[data-chat-author-path]')).toBeNull();
      expect(row(id).querySelector('.hdc-who')).toBeNull();
      expect(row(id).querySelector('.hdc-burst-gutter [data-chat-burst-time]')).not.toBeNull();
    }
    expect(row('xt:3').querySelector('[data-chat-author-path]')?.textContent).toContain('Fenrir');
    expect(row('xt:3').querySelector('[data-chat-dir="from"]')).not.toBeNull();
  });
});
