/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({ items: [] as unknown[], calls: [] as Array<{ path: string; method: string; body: string }> }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: String(init.body ?? '') });
      if (path === '/swarm/agents/1' && method === 'GET') {
        return { id: 1, display_name: 'SysOp', rank: 'alpha', state: 'awake', thread_key: 'all', session_id: null, tmux_session: null };
      }
      if (path.startsWith('/swarm/agents/1/conversation')) return { entries: [], cursor: null };
      if (path === '/swarm/agents/1/waiting') return { agent_id: 1, items: server.items, count: server.items.length };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import { agentPage } from '../agents/agent-page.svelte';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import { chatSlotId } from './chat-model';
import type { SwarmWaitingItem } from './chat-api';
import { feedTopic, kindOf, mixOf } from './waiting-model';
import { SETTLE_MS } from './waiting-store.svelte';

const NOW = 1_800_000_000;
const sysop = [{ kind: 'sysop', name: 'sysop', agent_id: 1 }];
const swarm = [{ kind: 'company', name: 'carnivore.ai', agent_id: 2 }, { kind: 'project', name: 'swarm', agent_id: 3 }];
const card = (id: number, ref: string): SwarmWaitingItem => ({
  kind: 'card', id: `card:item:${id}`, agent_id: 1, author_path: sysop, at: NOW - 2400,
  entry: {
    kind: 'card', id: `item:${id}`, at: NOW - 2400, card: 'question', author_path: sysop, waits_on_owner: true,
    item: { id, list: 'all', text: 'turn on the company "argent"?', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'question',
            revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [], swarm_ref: ref },
  } as never,
});
const review: SwarmWaitingItem = {
  kind: 'review', id: 'review:1714', agent_id: 3, author_path: swarm, at: NOW - 840,
  card: { id: 1714, title: 'waiting on you mockups', result: 'needs you: pick a mockup\n\nthree directions', revision: 9 },
};
const approval: SwarmWaitingItem = {
  kind: 'approval', id: 'approval:act_1', agent_id: 3, author_path: swarm, at: NOW - 60,
  approval: { id: 'act_1', source: 'action', host: 'local', session_id: 'ses_x', kind: 'agent_spawn', question: 'spawn a task agent', options: [], rows: [] } as never,
};

let app: object | null = null;

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(1) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW * 1000);
  server.items = [];
  server.calls = [];
  agentPage.id = null;
  resourcePush().store.hello({ resource_topics: ['swarm_agent', 'approvals', 'swarm_roster'] });
  registerCplugWidgets(huddleCplug);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the waiting tray', () => {
  test('no tray while nothing waits', async () => {
    const host = await mountChat();
    await vi.waitFor(() => expect(server.calls.some((c) => c.path === '/swarm/agents/1/waiting')).toBe(true));
    expect(host.querySelector('[data-waiting-tray]')).toBeNull();
  });

  test('sysop: count and a roll-up mix line collapsed; open groups by breadcrumb, own first; review accepts in place', async () => {
    server.items = [card(40, 'suggest:7'), review, approval];
    const host = await mountChat();
    await vi.waitFor(() => expect(host.querySelector('[data-waiting-tray]')).not.toBeNull());
    const tray = host.querySelector('[data-waiting-tray]') as HTMLElement;
    expect(tray.querySelector('[data-waiting-total]')?.textContent).toBe('3');
    expect(tray.querySelector('[data-waiting-mix]')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('here 1 · carnivore.ai 2');
    expect(tray.querySelector('[data-waiting-list]')).toBeNull();
    const compose = host.querySelector('[data-chat-compose]') as HTMLElement;
    expect(tray.compareDocumentPosition(compose) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    (tray.querySelector('[data-waiting-toggle]') as HTMLButtonElement).click();
    flushSync();
    const groups = [...tray.querySelectorAll('[data-waiting-group]')].map((g) => g.getAttribute('data-waiting-group'));
    expect(groups).toEqual(['1', '3']);
    expect(tray.querySelector('[data-waiting-kind="suggestion"] [data-huddle-item="40"]')).not.toBeNull();
    expect(tray.querySelector('[data-waiting-item="approval:act_1"] .hdc-wait-kind')?.textContent).toBe('approval');
    expect(tray.querySelector('[data-waiting-mix]')?.textContent).toContain('oldest 40m');

    server.items = [card(40, 'suggest:7'), approval];
    (tray.querySelector('[data-waiting-item="review:1714"] [data-waiting-accept]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(tray.querySelector('[data-waiting-item="review:1714"]')).toBeNull());
    const done = server.calls.find((c) => c.path === '/swarm/cards/1714/done');
    expect(done?.method).toBe('POST');
    expect(JSON.parse(done?.body ?? '{}')).toEqual({ expected_revision: 9 });
    expect(tray.querySelector('[data-waiting-total]')?.textContent).toBe('2');
  });

  test('a push frame naming the inbox re-reads the feed once, after it settles', async () => {
    const host = await mountChat();
    await vi.waitFor(() => expect(server.calls.filter((c) => c.path === '/swarm/agents/1/waiting').length).toBe(1));
    vi.useFakeTimers();
    server.items = [approval];
    resourcePush().store.frame({ topics: ['approvals'] });
    resourcePush().store.frame({ topics: ['swarm_agent:9'] });
    expect(server.calls.filter((c) => c.path === '/swarm/agents/1/waiting').length).toBe(1);
    await vi.advanceTimersByTimeAsync(SETTLE_MS + 10);
    vi.useRealTimers();
    await vi.waitFor(() => expect(host.querySelector('[data-waiting-total]')?.textContent).toBe('1'));
    expect(server.calls.filter((c) => c.path === '/swarm/agents/1/waiting').length).toBe(2);
  });
});

describe('the tray rules', () => {
  test('feed topics', () => {
    expect(['swarm_agent:3', 'swarm_roster', 'approvals', 'cplug.huddle.list:agent:3'].every(feedTopic)).toBe(true);
    expect(feedTopic('layouts')).toBe(false);
  });

  test('a plain chat mixes by kind', () => {
    expect(kindOf(card(1, 'trust:4:ab'))).toBe('trust');
    expect(kindOf(card(1, 'waiting:9'))).toBe('decision');
    expect(mixOf([card(1, 'question:3'), card(2, 'question:4'), review], 1, false)).toEqual([{ count: 2, kind: 'question' }, { count: 1, kind: 'review' }]);
  });
});
