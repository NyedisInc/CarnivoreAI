/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount, type Component } from 'svelte';

type Call = { path: string; method: string };
const server = vi.hoisted(() => ({ calls: [] as Call[], navigate: vi.fn(async () => true) }));

const AGENTS = [
  { id: 7, display_name: 'Loki', rank: 'project', state: 'awake', thread_key: '12', session_id: 'ses_9', tmux_session: 'cloude_loki' },
  { id: 8, display_name: 'Frigg', rank: 'feature', state: 'asleep', thread_key: 'agent:8', session_id: null, tmux_session: null },
  { id: 9, display_name: 'Odin', rank: 'task', state: 'torn_down', thread_key: 'agent:9', session_id: null, tmux_session: null },
];

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method });
      if (path === '/swarm/roster') return { agents: AGENTS, limits: {} };
      if (path === '/swarm/agents/7') return { ...AGENTS[0] };
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: [], cursor: null };
      if (path === '/swarm/agents/7/wake') return { state: 'waking', wake_id: 1, joined: false };
      if (path === '/swarm/agents/7/sleep') return { state: 'asleep', commit: {} };
      return {};
    },
  };
});

vi.mock('../../lib/sessions-search/host', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../lib/sessions-search/host')>();
  return { ...real, browserSessionsSearchHost: () => ({ navigate: server.navigate }) };
});

import { resourcePush } from '../../lib/resource-push/boot';
import { setLocale } from '../../lib/i18n/index.svelte';
import { MENU_PAGES, menuPage } from '../../lib/menu-page/menu-pages';
import { resetMenuPageShell, syncMenuPages, type ShellDeps } from '../../lib/menu-page/menu-page-shell.svelte';
import '../sdk';
import { registerCplugPage } from '../sdk/pages';
import { AGENT_PAGE, agentIdFromHash, agentPage } from './agents/agent-page.svelte';
import { swarmRoster, projectHasAgent, refreshRoster } from './agents/agent-roster.svelte';
import ChatWidget from './chat/ChatWidget.svelte';
import { chatSlotId } from './chat/chat-model';

// jsdom has no popover API; the one item menu shows its levels through it (#2613).
const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

setLocale('en');
let app: object | null = null;
const opened = vi.fn(() => true);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mountOn(component: Component<any>, props: Record<string, unknown> = {}): HTMLElement {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(component, { target: document.getElementById('host') as HTMLElement, props });
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  server.calls.length = 0;
  server.navigate.mockClear();
  opened.mockClear();
  swarmRoster.agents = [];
  agentPage.id = null;
  history.replaceState(null, '', '/');
  resourcePush().store.hello({ resource_topics: ['swarm_roster', 'swarm_agent'] });
  registerCplugPage(AGENT_PAGE, opened);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  delete (window as unknown as { App?: unknown }).App;
  vi.restoreAllMocks();
});

describe('the roster', () => {
  test('a project that has its agent is known, so the kebab does not offer to turn it on twice', async () => {
    await refreshRoster();
    expect(swarmRoster.agents.length).toBe(2);
    expect(projectHasAgent(12)).toBe(true);
    expect(projectHasAgent(13)).toBe(false);
    expect(projectHasAgent(null)).toBe(false);
  });
});

describe('the page keeps the drawer tab', () => {
  test('opening the agent page does not switch the drawer to the menu tab; another page still does', async () => {
    resetMenuPageShell();
    document.body.innerHTML = MENU_PAGES.map((p) => `<div id="${p.containerId}"></div>`).join('');
    const selectTab = vi.fn();
    const deps: ShellDeps = { selectTab, web: () => ({}) };
    expect(menuPage('huddle-agent')?.keepDrawerTab).toBe(true);
    expect(menuPage('settings')?.keepDrawerTab).toBeUndefined();
    document.getElementById('huddle-agent-screen')!.append(document.createElement('div'));
    syncMenuPages(document, deps);
    expect(selectTab).not.toHaveBeenCalled();
    document.getElementById('huddle-agent-screen')!.replaceChildren();
    document.getElementById('settings-screen')!.append(document.createElement('div'));
    syncMenuPages(document, deps);
    expect(selectTab).toHaveBeenCalledWith('menu');
    resetMenuPageShell();
  });

  test('the fragment names the agent, and only a real id', () => {
    expect(agentIdFromHash('#agent/12')).toBe(12);
    expect(agentIdFromHash('#agent/0')).toBeNull();
    expect(agentIdFromHash('#agent/x')).toBeNull();
    expect(agentIdFromHash('#settings')).toBeNull();
  });
});

describe('a wake or sleep from the chat never opens a terminal', () => {
  test('wake fresh and sleep call the Swarm routes and nothing opens or focuses a terminal', async () => {
    const focus = vi.fn(async () => {});
    (window as unknown as { App: unknown }).App = { returnToExistingTerminal: focus };
    const host = mountOn(ChatWidget, { instance: chatSlotId(7) });
    await vi.waitFor(() => expect(host.querySelector('[data-chat-state="ok"]')).not.toBeNull());
    host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    (document.querySelector('[data-node="sleep"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(server.calls.some((c) => c.path === '/swarm/agents/7/sleep' && c.method === 'POST')).toBe(true));
    await tick();
    expect(server.navigate).not.toHaveBeenCalled();
    expect(focus).not.toHaveBeenCalled();
  });
});
