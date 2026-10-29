/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

type Call = { path: string; method: string };
const server = vi.hoisted(() => ({ calls: [] as Call[] }));

const item = (id: number, list: string, text: string) => ({
  id, list, text, note: '', position: id, created_by: 'owner', state: 'open', kind: 'task', number: id, revision: 1,
  created_seq: id, seq: id, deleted: false, status: 'open', thread: [], unread: false,
});
const ITEMS: Record<string, ReturnType<typeof item>[]> = {
  'agent:5': [item(51, 'agent:5', 'loki task one'), item(52, 'agent:5', 'loki task two')],
  'agent:6': [item(61, 'agent:6', 'frigg secret task')],
};

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        const row = (key: string) => ({ key, name: key, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0, untold: false, waiting_to_send: 0 });
        return { cursor: 0, lists: [row('all'), row('agent:5'), row('agent:6')] };
      }
      if (path === '/cplugs/huddle/send') return { results: [{ list: 'agent:5', status: 'sent', target: 'ses_5', label: 'Loki' }] };
      if (/\/sessions$/.test(path)) return { sessions: [{ id: 'ses_5', label: 'Loki' }], default: 'ses_5', reason: 'only_session' };
      const list = /^\/cplugs\/huddle\/lists\/([^/?]+)(?:\?.*)?$/.exec(path);
      if (list) { const key = decodeURIComponent(list[1]!); return { list: key, revision: 1, cursor: 1, items: ITEMS[key] ?? [] }; }
      if (path === '/swarm/agents/5') return { id: 5, display_name: 'Loki', rank: 'project', state: 'awake', thread_key: 'agent:5', session_id: 'ses_5', tmux_session: 'cloude_loki' };
      if (path.startsWith('/swarm/agents/')) return { entries: [], cursor: null };
      return {};
    },
  };
});

const terminal = vi.hoisted(() => ({ opened: [] as number[] }));
vi.mock('../../cplugs/huddle/agents/agent-terminal', () => ({ openAgentTerminal: async (id: number) => { terminal.opened.push(id); return true; } }));

const drag = vi.hoisted(() => ({ calls: [] as unknown[][] }));
vi.mock('../../opscenter/layout-editor/drawer-drag', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/layout-editor/drawer-drag')>()),
  beginCardDrag: (...args: unknown[]) => { drag.calls.push(args); return true; },
}));

import { setLocale } from '../i18n/index.svelte';
import { registerCplugWidgets } from '../../cplugs/host/widgets';
import { huddleCplug } from '../../cplugs/huddle/index';
import { homeLayout } from '../../opscenter/engine/layout.svelte';
import { agentFromSearch, agentGeometryKey, agentPath, agentWindowName } from '../../popout/popout';
import { registerCplugPage } from '../../cplugs/sdk/pages';
import { AGENT_PAGE, agentPage, openAgentPage } from '../../cplugs/huddle/agents/agent-page.svelte';
import { huddle } from '../../cplugs/huddle/huddle.svelte';
import { AGGREGATE } from '../../cplugs/huddle/huddle-model';
import HuddleReply from '../../cplugs/huddle/HuddleReply.svelte';
import { openAgentDrawerHost } from './drawer-host';
import { agentDrawer, AGENT_DRAWER_DOCKED_CLASS, AGENT_DRAWER_WIDTH_KEY, closeAgentDrawer, dockBesideTerminal, drawerAnchorLeft, keepsDrawerOpen, widthFromPointer, leftDrawerWidth, setDrawerWidth } from './agent-drawer.svelte';
import { STORAGE_KEY as LEFT_WIDTH_KEY } from '../drawer/resize';

setLocale('en');
const mounted: object[] = [];
const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) { flushSync(); await tick(); await new Promise((r) => setTimeout(r, 0)); } };
const drawer = (): HTMLElement | null => document.querySelector<HTMLElement>('[data-agent-drawer]');

beforeEach(() => {
  document.body.innerHTML = '<div id="huddle-agent-screen"></div><div id="huddle-agent-drawer"></div>';
  localStorage.clear();
  server.calls.length = 0;
  agentPage.id = null;
  agentDrawer.id = null; agentDrawer.tab = 'chat'; agentDrawer.width = null;
  huddle.selected = AGGREGATE;
  registerCplugPage(AGENT_PAGE, openAgentDrawerHost);
});

afterEach(() => {
  while (mounted.length) unmount(mounted.pop() as object);
  closeAgentDrawer();
  document.body.innerHTML = '';
});

describe('the agent drawer', () => {
  test('an agent click slides the drawer out, not the full page, at the left drawer width; another click swaps it', async () => {
    localStorage.setItem(LEFT_WIDTH_KEY, '360');
    expect(openAgentPage(5)).toBe(true);
    await settle();
    expect(drawer()?.getAttribute('data-agent-drawer')).toBe('5');
    expect(document.querySelector('[data-huddle-agent-page]')).toBeNull();
    expect(location.hash).toBe('');
    expect(leftDrawerWidth()).toBe(360);
    expect(drawer()?.getAttribute('data-agent-drawer-width')).toBe('360');
    openAgentPage(6);
    await settle();
    expect(drawer()?.getAttribute('data-agent-drawer')).toBe('6');
    document.querySelector<HTMLElement>('[data-agent-drawer-close]')!.click();
    await settle();
    expect(drawer()).toBeNull();
  });

  test('Escape closes it, a drag width is remembered per device and survives a reload', async () => {
    openAgentPage(5);
    await settle();
    expect(drawer()?.getAttribute('data-agent-drawer-width')).toBe('320');
    setDrawerWidth(500, true);
    await settle();
    expect(drawer()?.getAttribute('data-agent-drawer-width')).toBe('500');
    expect(localStorage.getItem(AGENT_DRAWER_WIDTH_KEY)).toBe('500');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle();
    expect(drawer()).toBeNull();
    agentDrawer.width = null;
    openAgentPage(5);
    await settle();
    expect(drawer()?.getAttribute('data-agent-drawer-width')).toBe('500');
  });

  test('hiding the chat clears the selection the Swarm panel scopes by, on every close path; a reopen selects again', async () => {
    openAgentPage(5);
    await settle();
    expect(agentPage.id).toBe(5);
    (document.querySelector('[data-agent-drawer-close]') as HTMLButtonElement).click();
    await settle();
    expect(drawer()).toBeNull();
    expect(agentPage.id).toBeNull();
    openAgentPage(7);
    await settle();
    expect(agentPage.id).toBe(7);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle();
    expect(agentPage.id).toBeNull();
  });

  test('the Tasks Viewer shows only that agent\'s list, and leaves the list on screen as it was when it closes', async () => {
    openAgentPage(5);
    await settle();
    document.querySelector<HTMLElement>('[data-agent-drawer-tab="tasks"]')!.click();
    await settle();
    expect(huddle.selected).toBe('agent:5');
    const text = document.querySelector('[data-agent-drawer-tasks]')!.textContent ?? '';
    expect(text).toContain('loki task one');
    expect(text).toContain('loki task two');
    expect(text).not.toContain('frigg secret task');
    expect(document.querySelector('[data-huddle-pick]')).toBeNull();
    closeAgentDrawer();
    await settle();
    expect(huddle.selected).toBe(AGGREGATE);
  });
});

describe('a press outside hides the drawer (2026-10-07; pointerdown since #1404)', () => {
  const press = (el: Element): void => { el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true })); };

  test('outside closes on press (a click alone does not); inside, its menu, a popover it opened and an agent square keep it', async () => {
    const outside = document.body.appendChild(document.createElement('main'));
    const popover = document.body.appendChild(document.createElement('div'));
    popover.setAttribute('role', 'menu');
    const sidebar = document.body.appendChild(document.createElement('nav'));
    sidebar.className = 'session-sidebar-panel session-sidebar-panel--open';
    sidebar.innerHTML = '<button data-swarm-agent="6"><span class="sq"></span></button>';
    openAgentPage(5);
    await settle();
    const panel = drawer()!;
    outside.click();
    await settle();
    expect(drawer()).toBe(panel);
    press(panel.querySelector('[data-agent-drawer-grip]')!);
    press(popover);
    await settle();
    expect(drawer()).toBe(panel);
    (panel.querySelector('[data-chat-menu]') as HTMLButtonElement).click();
    await settle();
    press(panel.querySelector('[data-chat-menu-extra]')!);
    await settle();
    expect(drawer()).toBe(panel);
    press(sidebar.querySelector('.sq')!);
    openAgentPage(6);
    await settle();
    expect(drawer()).toBe(panel);
    expect(panel.getAttribute('data-agent-drawer')).toBe('6');
    press(outside);
    await settle();
    expect(drawer()).toBeNull();
  });

  test('a press on a ledger row or a chat crumb marked as an opener keeps the drawer for the in-place switch', async () => {
    const row = document.body.appendChild(document.createElement('button'));
    row.setAttribute('data-agent-drawer-opener', '');
    openAgentPage(5);
    await settle();
    press(row);
    await settle();
    expect(drawer()).not.toBeNull();
  });

  test('focus goes back to the opener on Escape or the close key, never on an outside press', async () => {
    const opener = document.body.appendChild(document.createElement('button'));
    const outside = document.body.appendChild(document.createElement('main'));
    const focus = vi.spyOn(opener, 'focus');
    opener.focus();
    openAgentPage(5);
    await settle();
    focus.mockClear();
    press(outside);
    await settle();
    expect(drawer()).toBeNull();
    expect(focus).not.toHaveBeenCalled();
    opener.focus();
    openAgentPage(5);
    await settle();
    focus.mockClear();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();
    expect(drawer()).toBeNull();
    expect(focus).toHaveBeenCalledTimes(1);
    opener.focus();
    openAgentPage(5);
    await settle();
    focus.mockClear();
    drawer()!.querySelector<HTMLButtonElement>('[data-agent-drawer-close]')!.click();
    await settle();
    expect(drawer()).toBeNull();
    expect(focus).toHaveBeenCalledTimes(1);
  });
});

describe('a reply is sent, never queued', () => {
  test('Enter in a list item\'s reply box saves the reply, then tells at once, and no waiting-to-send state appears', async () => {
    document.body.innerHTML = '<div id="host"></div>';
    mounted.push(mount(HuddleReply, { target: document.getElementById('host') as HTMLElement, props: { item: item(51, 'agent:5', 'x') as never } }));
    await settle();
    const box = document.querySelector<HTMLTextAreaElement>('[data-huddle-reply="51"]')!;
    box.value = 'go ahead';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    const writes = server.calls.filter((c) => c.method !== 'GET').map((c) => c.path);
    expect(writes).toEqual(['/cplugs/huddle/items/51/messages', '/cplugs/huddle/send']);
    box.value = 'again';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true }));
    await settle();
    expect(document.body.textContent).not.toMatch(/queue|waiting to send/);
  });
});

describe('taking the chat out of the drawer (#1363 slice B)', () => {
  const placed = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
  const menu = async (): Promise<void> => { document.querySelector<HTMLElement>('[data-agent-drawer] [data-chat-menu]')!.click(); await settle(); };

  beforeEach(() => {
    registerCplugWidgets(huddleCplug);
    homeLayout.resetAll();
    drag.calls.length = 0;
  });

  test('make widget adds a chat widget bound to the agent, remembered in the layout, and closes the drawer', async () => {
    openAgentPage(5);
    await settle();
    await menu();
    document.querySelector<HTMLElement>('[data-chat-menu-extra="widget"]')!.click();
    await settle();
    expect(placed()).toContain('huddle.chat:agent:5');
    const rows = homeLayout.state.layout.rows;
    expect(rows[rows.length - 1]!.slots.map((slot) => slot.id)).toEqual(['huddle.chat:agent:5']);
    expect(drawer()).toBeNull();
    openAgentPage(5);
    await settle();
    await menu();
    document.querySelector<HTMLElement>('[data-chat-menu-extra="widget"]')!.click();
    await settle();
    expect(placed().filter((id) => id === 'huddle.chat:agent:5')).toHaveLength(1);
    expect(drawer()).not.toBeNull();
  });

  test('the drawer is anchored at the left drawer\'s right edge, and a pointer sets the width from that edge', () => {
    expect(drawerAnchorLeft()).toBe(0);
    document.body.insertAdjacentHTML('beforeend', '<div class="session-sidebar-panel session-sidebar-panel--open"></div>');
    const panel = document.querySelector('.session-sidebar-panel--open')!;
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({ right: 320 } as DOMRect);
    expect(drawerAnchorLeft()).toBe(320);
    expect(widthFromPointer(700, drawerAnchorLeft())).toBe(380);
  });

  test('pop out opens the pop-out url of the same agent, sized like the drawer (held to the pop-out minimum)', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus() {} } as unknown as Window);
    openAgentPage(6);
    await settle();
    await menu();
    document.querySelector<HTMLElement>('[data-chat-menu-extra="popout"]')!.click();
    await settle();
    const [url, name, features] = open.mock.calls[0] as [string, string, string];
    expect(agentFromSearch(url.slice(url.indexOf('?')))).toBe(6);
    expect(url).toBe(agentPath(6));
    expect(name).toBe(agentWindowName(6));
    expect(features).toContain('width=360');
    expect(agentGeometryKey(6)).toContain('.6.');
    expect(agentFromSearch('?agent=abc')).toBeNull();
    open.mockRestore();
  });

  test('the kebab menu lists "agent terminal"; it opens that agent\'s terminal and closes the drawer', async () => {
    terminal.opened.length = 0;
    openAgentPage(5);
    await settle();
    await menu();
    const item = document.querySelector<HTMLElement>('[data-chat-menu-extra="terminal"]')!;
    expect(item.textContent).toContain('agent terminal');
    item.click();
    await settle();
    expect(terminal.opened).toEqual([5]);
    expect(drawer()).toBeNull();
  });

  test('dragging the title row starts the engine card drag for this agent, and a drop lands it at the target', async () => {
    openAgentPage(5);
    await settle();
    const bar = document.querySelector<HTMLElement>('[data-agent-frame-bar] [data-chat-bar]')!;
    bar.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, pointerId: 1 }));
    expect(drag.calls).toHaveLength(1);
    const [el, , id, store, page, panel, handlers] = drag.calls[0] as [HTMLElement, unknown, string, unknown, string, HTMLElement, { onDrop: (t: unknown) => void }];
    expect(el).toBe(bar);
    expect([id, store, page]).toEqual(['huddle.chat:agent:5', homeLayout, 'home']);
    expect(panel).toBe(drawer());
    handlers.onDrop({ kind: 'new', after: null });
    await settle();
    expect(placed()).toContain('huddle.chat:agent:5');
    expect(drawer()).toBeNull();
  });
});

describe('#1408: the open drawer docks beside the terminal', () => {
  const wide = (px: number): void => { Object.defineProperty(window, 'innerWidth', { configurable: true, value: px }); };
  afterEach(() => { dockBesideTerminal(false, 0); wide(1024); });

  test('at 1024 px and wider the terminal starts at the drawer right edge, and is refit; closed, the offset goes back', () => {
    const fits: string[] = [];
    (window as { TerminalLayout?: unknown }).TerminalLayout = { requestFit: (why: string) => fits.push(why) };
    wide(1440);
    expect(dockBesideTerminal(true, 360)).toBe(true);
    expect(document.body.classList.contains(AGENT_DRAWER_DOCKED_CLASS)).toBe(true);
    expect(document.body.style.getPropertyValue('--dock-offset')).toBe('360px');
    expect(dockBesideTerminal(false, 360)).toBe(false);
    expect(document.body.classList.contains(AGENT_DRAWER_DOCKED_CLASS)).toBe(false);
    expect(document.body.style.getPropertyValue('--dock-offset')).toBe('');
    expect(fits).toEqual(['agent-drawer-dock', 'agent-drawer-dock']);
    delete (window as { TerminalLayout?: unknown }).TerminalLayout;
  });

  test('below 1024 px the drawer stays an overlay', () => {
    wide(820);
    expect(dockBesideTerminal(true, 360)).toBe(false);
    expect(document.body.classList.contains(AGENT_DRAWER_DOCKED_CLASS)).toBe(false);
  });

  test('docked, a press in the terminal keeps the chat; anywhere else outside still closes it; undocked the terminal closes it', () => {
    document.body.insertAdjacentHTML('beforeend', '<div id="terminal-screen"><canvas id="t"></canvas></div><div id="elsewhere"></div>');
    const term = document.getElementById('t');
    wide(1440);
    dockBesideTerminal(true, 360);
    expect(keepsDrawerOpen(term)).toBe(true);
    expect(keepsDrawerOpen(document.getElementById('elsewhere'))).toBe(false);
    dockBesideTerminal(false, 360);
    expect(keepsDrawerOpen(term)).toBe(false);
  });
});
