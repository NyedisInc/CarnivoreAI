/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import authorPathSource from './AuthorPath.svelte?raw';
import chatCardSource from './ChatCard.svelte?raw';

const server = vi.hoisted(() => ({ entries: [] as unknown[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (path === '/swarm/agents/1' && method === 'GET') {
        return { id: 1, display_name: 'SysOp', rank: 'alpha', state: 'awake', thread_key: 'all', session_id: null, tmux_session: null };
      }
      if (path.startsWith('/swarm/agents/1/conversation')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import { agentPage } from '../agents/agent-page.svelte';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import { chatSlotId, headOf } from './chat-model';

let app: object | null = null;
const NOW = 1_800_000_000;

const research = [
  { kind: 'company', name: 'Nyedis', agent_id: 3 },
  { kind: 'project', name: 'Orchardco', agent_id: null },
  { kind: 'agent', name: 'Orchard-Research', agent_id: 9 },
];
const askCard = (askers: unknown[]) => ({
  kind: 'card', id: 'item:196', at: NOW - 600, card: 'question', author_path: research,
  item: {
    id: 196, list: 'all', text: 'Orchard-Research asked: "raw words"', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'question',
    revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'question', thread: [], swarm_ref: 'question:196',
  },
  question: {
    summary: 'keep the old dlp vendor for one more quarter?', task: 'researching new dlp providers',
    details: 'NOTE 1 red proof as ordered is impossible.', askers, asked_at: NOW - 240,
  },
});
const asker = (name: string, id: number | null, path: unknown[] = [{ kind: 'agent', name, agent_id: id }]) => ({ agent_id: id, name, author_path: path });

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(1) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW * 1000);
  server.entries = [];
  agentPage.id = null;
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
  registerCplugWidgets(huddleCplug);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('the question card', () => {
  test('path with +N and the time since, then task, summary, a full details toggle; no title row, no "asked:" prefix', async () => {
    server.entries = [askCard([asker('Orchard-Research', 9, research), asker('Orchard-QnA', 11), asker('Gone-Agent', null)])];
    const host = await mountChat();
    const card = host.querySelector('[data-huddle-item="196"]') as HTMLElement;
    const crumbs = [...card.querySelectorAll('[data-chat-author-path] nav > .hdc-crumb')].map((c) => c.textContent?.trim());
    expect(crumbs).toEqual(['Nyedis', 'Orchardco', 'Orchard-Research']);
    expect(card.querySelector('[data-chat-askers-more]')?.textContent).toBe('+2');
    expect(card.querySelector('[data-chat-since]')?.textContent).toBe('4m');
    expect(card.querySelector('[data-chat-ask-task]')?.textContent).toContain('researching new dlp providers');
    expect(card.querySelector('[data-chat-ask-summary]')?.textContent).toBe('keep the old dlp vendor for one more quarter?');
    expect(card.querySelector('.hdc-card-head')).toBeNull();
    expect(card.classList.contains('hdc-card--ask')).toBe(true);
    expect(card.textContent).not.toContain('a question for you');
    expect(card.textContent).not.toContain('asked:');
    expect(card.querySelector('[data-chat-ask-details]')).toBeNull();
    const toggle = card.querySelector('[data-chat-ask-details-toggle]') as HTMLButtonElement;
    expect(toggle.textContent).toBe('full details');
    toggle.click();
    flushSync();
    const details = card.querySelector('[data-chat-ask-details]') as HTMLElement;
    expect(details.textContent).toContain('NOTE 1 red proof as ordered is impossible.');
    expect([...details.querySelectorAll('[data-chat-ask-askers] .hdc-crumb-name')].map((n) => n.textContent)).toEqual(['Orchard-QnA', 'Gone-Agent']);
    expect(details.querySelector('[data-chat-ask-routing]')).toBeNull();
    expect(details.textContent).not.toMatch(/routing|checked on the way up/);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    toggle.click();
    flushSync();
    expect(card.querySelector('[data-chat-ask-details]')).toBeNull();
    expect(card.querySelector('textarea, input')).toBeNull();
    expect(card.closest('[data-entry-id]')?.querySelector(':scope > [data-chat-quote]')).not.toBeNull();
  });

  test('a single asker shows no +N', async () => {
    server.entries = [askCard([asker('Orchard-Research', 9, research)])];
    const host = await mountChat();
    expect(host.querySelector('[data-chat-askers-more]')).toBeNull();
  });
});

describe('the header row on every message', () => {
  test('a live crumb opens that agent\'s chat; a crumb with no live agent is plain text; the owner gets no name line', async () => {
    server.entries = [
      askCard([asker('Orchard-Research', 9, research)]),
      { kind: 'owner', id: 'msg:1', at: NOW - 30, text: 'go', author_path: [{ kind: 'owner', name: 'acme', agent_id: null }] },
      { kind: 'agent', id: 'ag:1', at: NOW - 7200, text: 'done', author_path: [{ kind: 'sysop', name: 'SysOp', agent_id: 1 }] },
    ];
    const host = await mountChat();
    const card = host.querySelector('[data-huddle-item="196"]') as HTMLElement;
    expect(card.querySelector('button[data-crumb-kind="project"], span[data-crumb-kind="project"]')?.tagName).toBe('SPAN');
    const company = card.querySelector('[data-crumb-kind="company"]') as HTMLElement;
    expect(company.tagName).toBe('BUTTON');
    company.click();
    expect(agentPage.id).toBe(3);
    (card.querySelector('[data-crumb-kind="agent"]') as HTMLButtonElement).click();
    expect(agentPage.id).toBe(9);
    const owner = host.querySelector('[data-entry-id="msg:1"]') as HTMLElement;
    expect(owner.querySelector('[data-crumb-kind="owner"], .hdc-crumb-name')).toBeNull();
    expect(owner.querySelector('[data-chat-dir]')?.getAttribute('data-chat-dir')).toBe('none');
    expect(owner.querySelector('[data-chat-burst-time]')?.textContent).toBe('30s');
    const sysop = host.querySelector('[data-entry-id="ag:1"]') as HTMLElement;
    expect(sysop.querySelectorAll('.hdc-crumb-name')).toHaveLength(0);
    expect(sysop.querySelector('[data-chat-dir]')?.getAttribute('data-chat-dir')).toBe('none');
    expect(sysop.querySelector('[data-chat-burst-time]')?.textContent).toBe('2h');
  });

  test('the crumb row stays one line in a 320 px drawer: names shrink with an ellipsis and carry no tooltip (#1404, #1209)', async () => {
    server.entries = [askCard([asker('Orchard-Research', 9, research), asker('Orchard-QnA', 11)])];
    const host = await mountChat();
    const card = host.querySelector('[data-huddle-item="196"]') as HTMLElement;
    const names = [...card.querySelectorAll('[data-chat-author-path] nav .hdc-crumb-name')] as HTMLElement[];
    expect(names.map((n) => n.textContent)).toEqual(['Nyedis', 'Orchardco', 'Orchard-Research']);
    expect(names.every((n) => n.title === '')).toBe(true);
    expect([...card.querySelectorAll('.hdc-crumb--link')].every((b) => b.hasAttribute('data-agent-drawer-opener'))).toBe(true);
    const css = authorPathSource;
    const rule = (sel: string): string => css.match(new RegExp(`\\n\\s*\\${sel}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
    expect(rule('.hdc-path-crumbs')).toMatch(/flex-wrap:\s*nowrap/);
    expect(rule('.hdc-path-crumbs')).toMatch(/min-width:\s*0/);
    for (const sel of ['.hdc-path-sep', '.hdc-path-more', '.hdc-path-time']) expect(rule(sel)).toMatch(/flex:\s*none/);
    expect(rule('.hdc-crumb-name')).toMatch(/text-overflow:\s*ellipsis/);
  });

  test('the pure rules: no path, no header', () => {
    expect(headOf({ kind: 'agent', id: 'a', at: 1, text: 'x' })).toBeNull();
    expect(headOf({ kind: 'agent', id: 'a', at: 1, text: 'x', author_path: [] })).toBeNull();
  });
});

describe('question card spacing', () => {
  test('the stacked lines of a question card sit apart by a real gap token, wider than the card default', () => {
    const rule = /\.hdc-card--ask\s*\{([^}]*)\}/.exec(chatCardSource);
    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/gap:\s*var\(--oc-space-[3-9]\)/);
  });
});
