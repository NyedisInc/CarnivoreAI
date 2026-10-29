/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({ entries: [] as unknown[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (path === '/swarm/agents/7' && method === 'GET') {
        return { id: 7, display_name: 'Loki', rank: 'project', state: 'awake', thread_key: '12', session_id: null, tmux_session: null };
      }
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import HuddleAgentScreen from '../../../lib/huddle-agent/HuddleAgentScreen.svelte';
import { agentPage } from '../agents/agent-page.svelte';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import chatAvatarSource from './ChatAvatar.svelte?raw';
import { chatSlotId, decisionOf, draws, needsOwner } from './chat-model';

let app: object | null = null;

const item = (id: number, over: Record<string, unknown> = {}) => ({
  id, list: 'agent:7', text: `ship ${id}`, note: '', position: 1, created_by: 'claude', state: 'open', kind: 'done', revision: 1,
  created_seq: 1, seq: 1, deleted: false, status: 'review', thread: [], ...over,
});
const card = (id: number, over: Record<string, unknown> = {}, kind = 'done') => ({ kind: 'card', id: `item:${id}`, at: 1, card: kind, item: item(id, over) });
const traffic = (id: number, status: string | null, over: Record<string, unknown> = {}) => ({
  kind: 'traffic', id: `xt:${id}`, at: 2, direction: 'out', peer: 'Fenrir', text: `message ${id}`, thread: 't', in_reply_to: null,
  receipt: status ? { status, reason: null, delivered_at: null } : null, ...over,
});
const event = (name: string, text: string) => ({ kind: 'event', id: `ev:${name}:1`, at: 3, event: name, ref: '1', text });

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
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

describe('every entry renders a card or nothing', () => {
  test('no list item is ever empty, whatever the kind; an unknown kind with no words is dropped', async () => {
    server.entries = [
      { kind: 'owner', id: 'msg:1', at: 1, text: 'go' },
      { kind: 'agent', id: 'msg:2', at: 1, text: '   ' },
      { kind: 'mystery', id: 'x:1', at: 1 },
      { kind: 'mystery', id: 'x:2', at: 1, text: 'a new kind spoke' },
      { kind: 'event', id: 'ev:none:1', at: 1, event: 'none', ref: '1', text: '' },
      card(1),
      traffic(1, 'queued'),
      event('spawned', 'Boss spawned Fixer'),
    ];
    const host = await mountChat();
    const rows = [...host.querySelectorAll('[data-chat-entry]')];
    expect(rows.length).toBe(5);
    for (const row of rows) expect((row.textContent ?? '').trim().length).toBeGreaterThan(0);
    expect(host.textContent).toContain('a new kind spoke');
    expect(draws(server.entries[2] as never)).toBe(false);
  });
});

describe('the traffic card', () => {
  test('shows each receipt status', async () => {
    const statuses = ['queued', 'held', 'delivering', 'delivered', 'failed', 'expired'];
    server.entries = statuses.map((s, i) => traffic(i + 1, s, s === 'failed' ? { receipt: { status: 'failed', reason: 'peer is gone' } } : {}));
    server.entries.push(traffic(9, null, { direction: 'in', peer: 'Odin' }));
    const host = await mountChat();
    for (const status of statuses) {
      expect(host.querySelector(`[data-traffic-status="${status}"]`)?.textContent).toContain(status);
    }
    expect(host.querySelector('[data-traffic-status="failed"]')?.textContent).toContain('peer is gone');
    const incoming = host.querySelector('[data-chat-traffic="in"]') as HTMLElement;
    expect(incoming.querySelector('[data-traffic-status]')).toBeNull();
  });

  test('a received message shows its sender\'s node, a sent one this agent\'s node plus the recipient chip, no arrow (#2612)', async () => {
    server.entries = [traffic(1, 'delivered'), traffic(2, 'delivered', { direction: 'in', peer: 'Odin' })];
    const host = await mountChat();
    const gutterLabel = (row: Element): string => row.querySelector('.hdc-burst-gutter [aria-label]')?.getAttribute('aria-label') ?? '';
    const out = host.querySelector('[data-chat-traffic="out"]')?.closest('[data-chat-entry]') as HTMLElement;
    expect(gutterLabel(out)).toContain('Loki');
    expect(gutterLabel(out)).not.toContain('Fenrir');
    const chip = out.querySelector('[data-chat-traffic="out"] [data-chat-recipient]') as HTMLElement;
    expect(chip.textContent?.trim()).toBe('Fenrir');
    expect(chip.querySelector('[aria-label]')?.getAttribute('aria-label')).toContain('Fenrir');
    const inRow = host.querySelector('[data-chat-traffic="in"]')?.closest('[data-chat-entry]') as HTMLElement;
    expect(gutterLabel(inRow)).toContain('Odin');
    expect(inRow.querySelector('[data-chat-recipient]')).toBeNull();
    expect(host.querySelector('[data-chat-dir="to"]')).toBeNull();
    for (const el of host.querySelectorAll('[aria-label]')) expect(el.getAttribute('aria-label')).not.toMatch(/sent to this agent|from this agent/);
  });
});

describe('the event card', () => {
  test('an unknown event kind renders from its text, labelled by its own name', async () => {
    server.entries = [event('rallied', 'the swarm rallied at dawn'), event('spawned', 'Boss spawned Fixer')];
    const host = await mountChat();
    const odd = host.querySelector('[data-chat-event="rallied"]') as HTMLElement;
    expect(odd.textContent).toContain('the swarm rallied at dawn');
    expect(odd.textContent).toContain('rallied');
    expect(host.querySelector('[data-chat-event="spawned"]')?.textContent).toContain('Boss spawned Fixer');
  });
});

describe('a decided card', () => {
  test('shows its decision and no buttons, from the status or from the stored state', async () => {
    server.entries = [card(1, { status: 'done', state: 'done' }), card(2, { status: 'review', state: 'done', note: 'n' }), card(3)];
    const host = await mountChat();
    const decided = (id: number) => host.querySelector(`[data-huddle-item="${id}"]`) as HTMLElement;
    expect(decided(1).querySelector('[data-chat-decision="done"]')).not.toBeNull();
    expect(decided(2).querySelector('[data-chat-decision="done_with_note"]')).not.toBeNull();
    for (const id of [1, 2]) {
      expect(decided(id).querySelectorAll('button').length).toBe(0);
      expect(decided(id).querySelector('textarea')).toBeNull();
    }
    expect(decided(3).querySelectorAll('.hdc-card-keys button').length).toBe(2);
    expect(decisionOf(item(4, { status: 'review', state: 'done' }) as never)).toBe('done');
    expect(needsOwner(card(2, { status: 'review', state: 'done', note: 'n' }) as never)).toBe(false);
  });

  test('an open card has no reply box of its own; its quote key is the reply (#1435)', async () => {
    server.entries = [card(1)];
    const host = await mountChat();
    expect(host.querySelector('[data-huddle-reply="1"]')).toBeNull();
    expect(host.querySelector('[data-huddle-item="1"]')?.closest('[data-entry-id]')?.querySelector(':scope > [data-chat-quote]')).not.toBeNull();
  });
});

describe('the agent side of the conversation', () => {
  test('agent entries sit on the other side from the owner, under the agent name', async () => {
    server.entries = [
      { kind: 'owner', id: 'msg:1', at: 1, text: 'who are you' },
      { kind: 'agent', id: 'msg:2', at: 2, text: 'I am Loki' },
    ];
    const host = await mountChat();
    const agent = host.querySelector('.hdc-msg--agent') as HTMLElement;
    const owner = host.querySelector('.hdc-msg--owner') as HTMLElement;
    expect(agent.querySelector('.hdc-who')?.textContent).toBe('Loki');
    expect(owner.querySelector('.hdc-who')?.textContent).toBe('you');
    expect(agent.className).not.toBe(owner.className);
  });
});

describe('the agent page title', () => {
  test('is the agent display name, not the generic word', async () => {
    agentPage.id = 7;
    document.body.innerHTML = '<div id="host"></div>';
    app = mount(HuddleAgentScreen, { target: document.getElementById('host') as HTMLElement, props: { embedded: true } });
    await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
    flushSync();
    const title = document.querySelector('.pl-title, .mf-title, h1, h2');
    expect(title?.textContent?.trim().toLowerCase()).toBe('loki');
  });
});

describe('the chat avatars', () => {
  test('no frame around any avatar: no owner hairline, no identicon border, no node halo (Alex, 2026-10-27, card 1505)', () => {
    const css = chatAvatarSource.slice(chatAvatarSource.indexOf('<style>'));
    expect(css).not.toMatch(/\.hdc-av-you\s*\{[^}]*(box-shadow|border:|outline)/);
    expect(css).toMatch(/\.hdc-av :global\(\.pk-gw\) \{ display: none; \}/);
    expect(css).toMatch(/\.hdc-av :global\(\.ident\) \{ border: 0; \}/);
  });
});
