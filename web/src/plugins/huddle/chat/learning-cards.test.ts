/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

type Call = { path: string; method: string; body: unknown };
const server = vi.hoisted(() => ({ calls: [] as Call[], entries: [] as unknown[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/swarm/agents/7' && method === 'GET') {
        return { id: 7, display_name: 'Loki', rank: 'project', state: 'awake', thread_key: '12', session_id: null, tmux_session: null };
      }
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      if (method === 'DELETE') return { reopened_question_ids: [4] };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import { cardVariant, chatSlotId } from './chat-model';

let app: object | null = null;

const item = (id: number, swarmRef: string, kind = 'question') => ({
  id, list: 'agent:7', text: `text ${id}`, note: '', position: 1, created_by: 'claude', state: 'open', kind, revision: 1,
  created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [], swarm_ref: swarmRef,
});
const cardEntry = (id: number, swarmRef: string, kind = 'question') => ({ kind: 'card', id: `item:${id}`, at: 1, card: kind, item: item(id, swarmRef, kind) });

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  server.calls.length = 0;
  server.entries = [];
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
  registerCplugWidgets(huddleCplug);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('cards are told apart by swarm_ref, not by kind', () => {
  test('question: and withdrawn: get their own look; the promotion receipt (S5b) is its own look, never the question card', async () => {
    expect(cardVariant(item(1, 'question:4') as never)).toBe('ask');
    expect(cardVariant(item(2, 'withdrawn:4', 'info') as never)).toBe('withdrawn');
    expect(cardVariant(item(3, 'promotion:9') as never)).toBe('promotion');
    server.entries = [cardEntry(1, 'question:4'), cardEntry(2, 'withdrawn:4', 'info'), cardEntry(3, 'promotion:9')];
    const host = await mountChat();
    expect(host.querySelector('[data-huddle-item="1"]')?.getAttribute('data-chat-card')).toBe('ask');
    expect(host.querySelector('[data-huddle-item="1"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="1"] .hdc-card-hint')).toBeNull();
    expect(host.querySelector('[data-huddle-item="2"]')?.getAttribute('data-chat-card')).toBe('withdrawn');
    expect(host.querySelector('[data-huddle-item="3"]')?.getAttribute('data-chat-card')).toBe('promotion');
  });
});

