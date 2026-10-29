/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const door = vi.hoisted(() => ({
  openSession: vi.fn(async () => true),
  authFetch: vi.fn(async (_path: string, _init?: RequestInit): Promise<unknown> => ({})),
  openCplugPage: vi.fn((_key: string) => true),
}));
vi.mock('../../sdk/sessions.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../sdk/sessions.svelte')>()), openSession: door.openSession, terminalAvailable: () => true,
}));
vi.mock('../../sdk/pages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../sdk/pages')>()), openCplugPage: door.openCplugPage,
}));
vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>()), authFetch: door.authFetch,
}));

import { setLocale } from '../../../lib/i18n/index.svelte';
import { swarmRoster } from '../agents/agent-roster.svelte';
import { openAgentTerminal } from '../agents/agent-terminal';
import { AGENT_PAGE, agentPage, openAgentPage } from '../agents/agent-page.svelte';
import SwarmPanel from './SwarmPanel.svelte';
import { buildFloor } from './floor';
import type { PanelAgent } from './panel-state';
import { openFloorTarget } from './swarm-live.svelte';

setLocale('en');
const here = path.dirname(fileURLToPath(import.meta.url));
const ROSTER: PanelAgent[] = [
  { id: 4, display_name: 'A very long agent name that cannot fit one line', rank: 'feature', state: 'awake', thread_key: 'agent:4', session_id: 'ses_4', tmux_session: 'cloude_loki' } as PanelAgent,
];

afterEach(() => { document.body.innerHTML = ''; door.openSession.mockClear(); door.openCplugPage.mockClear(); door.authFetch.mockReset(); swarmRoster.agents = []; });

describe('PANELWRAP', () => {
  test('the grid densities wrap a name to two lines and hang squares from the top; detailed keeps its one line', () => {
    const src = fs.readFileSync(path.join(here, 'SwarmPanel.svelte'), 'utf8');
    const nm = /\.pkp:not\(\[data-density='detailed'\]\) \.pkp-nm\s*\{([^}]*)\}/.exec(src)?.[1] ?? '';
    expect(nm).toMatch(/-webkit-line-clamp:\s*2/);
    expect(nm).toMatch(/white-space:\s*normal/);
    expect(nm).toMatch(/overflow-wrap:\s*break-word/);
    expect(/\.pkp:not\(\[data-density='detailed'\]\) \.pkp-grid\s*\{[^}]*align-items:\s*start/.test(src)).toBe(true);
    expect(/\.pkp-nm\s*\{[^}]*white-space:\s*nowrap/.test(src)).toBe(true);
  });

  test('shift-click on a square asks for the terminal, a plain click does not', () => {
    document.body.innerHTML = '<div id="host"></div>';
    const onOpen = vi.fn();
    const app = mount(SwarmPanel, { target: document.getElementById('host') as HTMLElement, props: {
      floor: buildFloor({ agents: ROSTER, sessions: [], companies: [], projects: [], showInactive: true, rowOf: () => ({ activity_status: 'idle' }) }),
      agents: ROSTER, density: 'expanded', now: 1, still: true, showInactive: true, onToggleInactive: vi.fn(), onOpen } });
    flushSync();
    const square = document.querySelector<HTMLElement>('[data-swarm-agent="4"]')!;
    square.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    square.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    expect(onOpen.mock.calls.map((c) => c[1])).toEqual([false, true]);
    expect(onOpen.mock.calls[0]![0]).toMatchObject({ kind: 'agent', agentId: 4 });
    unmount(app);
  });

  test('the terminal door opens the roster session through the drawer row switch, and never wakes an awake agent', async () => {
    swarmRoster.agents = ROSTER as never;
    expect(await openAgentTerminal(4)).toBe(true);
    expect(door.openSession).toHaveBeenCalledWith('ses_4', 'cloude_loki');
    door.openSession.mockClear();
    expect(await openAgentTerminal(99)).toBe(false);
    expect(door.authFetch).not.toHaveBeenCalled();
  });

  test('TERMFIX: an asleep agent is woken through the Swarm wake, then its terminal opens on the woken session', async () => {
    swarmRoster.agents = [{ ...ROSTER[0]!, state: 'asleep', session_id: null, tmux_session: null }] as never;
    let woke = false;
    door.authFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/swarm/agents/4/wake' && init?.method === 'POST') { woke = true; return { state: 'awake', wake_id: 1, joined: false }; }
      if (path === '/swarm/roster') return { agents: [woke ? ROSTER[0] : { ...ROSTER[0]!, state: 'asleep', session_id: null, tmux_session: null }], threads_ready: true };
      throw new Error(`unexpected ${path}`);
    });
    expect(await openAgentTerminal(4)).toBe(true);
    expect(woke).toBe(true);
    expect(door.openSession).toHaveBeenCalledWith('ses_4', 'cloude_loki');
  });

  test('TERMFIX: a refused wake opens nothing and never throws', async () => {
    swarmRoster.agents = [{ ...ROSTER[0]!, state: 'asleep', session_id: null, tmux_session: null }] as never;
    door.authFetch.mockRejectedValue(new Error('409 swarm_refused'));
    expect(await openAgentTerminal(4)).toBe(false);
    expect(door.openSession).not.toHaveBeenCalled();
  });

  test('openFloorTarget routes shift to the terminal door and plain to the chat page', () => {
    swarmRoster.agents = ROSTER as never;
    openFloorTarget({ kind: 'agent', agentId: 4 }, true);
    expect(door.openSession).toHaveBeenCalledTimes(1);
  });

  test('#2618: a plain click on an agent (crumb, row, square, Swarm node) opens its chat and leaves the current view alone', async () => {
    swarmRoster.agents = ROSTER as never;
    const before = location.hash;
    openFloorTarget({ kind: 'agent', agentId: 4 });
    expect(door.openCplugPage).toHaveBeenCalledWith(AGENT_PAGE);
    expect(agentPage.id).toBe(4);
    expect(openAgentPage(4)).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(door.openSession).not.toHaveBeenCalled();
    expect(location.hash).toBe(before);
  });

  test('#1408: a click on an asleep agent opens its chat alone and never wakes it', async () => {
    swarmRoster.agents = [{ ...ROSTER[0]!, state: 'asleep', session_id: null, tmux_session: null }] as never;
    expect(openAgentPage(4)).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(door.openCplugPage).toHaveBeenCalledWith(AGENT_PAGE);
    expect(door.openSession).not.toHaveBeenCalled();
    expect(door.authFetch).not.toHaveBeenCalled();
  });

  test('#1408: the Swarm page sends a node\'s plain click to the shared opener, never the terminal alone', () => {
    const src = fs.readFileSync(path.join(here, '../../../lib/huddle-swarm/SwarmPage.svelte'), 'utf8');
    const opens = [...src.matchAll(/onOpen=\{([^}]*)\}/g)].map((m) => m[1]);
    expect(opens.length).toBe(3);
    for (const handler of opens) expect(handler).not.toMatch(/true\s*\)/);
  });
});
