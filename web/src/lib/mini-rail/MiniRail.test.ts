/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import MiniRail from './MiniRail.svelte';
import { approvals } from '../approvals/approvals.svelte';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import { activeFlyout, closeFlyout } from '../sidebar-widgets/flyout.svelte';
import { MENU_FLYOUT, QUESTIONS_FLYOUT, SESSION_LIST_WIDGET } from '../sidebar-widgets/widget-ids';
import { buildRailSections } from './sections';
import type { SidebarRow } from '../sidebar-shell/legacy';
import * as GroupStore from '../drawer/group-store';
import * as Store from '../drawer/store';
import { rowHost } from '../sidebar-shell/row-host';
import '../dynamic-tabs/builtin';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import type { Resource } from '../../opscenter/api/poll.svelte';
import type { SessionTokenUsage } from '../../opscenter/api/types';

installPopoverPolyfill();

const usageMocks = vi.hoisted(() => ({ sessionUsage: vi.fn(), releaseSessionUsage: vi.fn() }));
vi.mock('../../opscenter/api/session-usage.svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../opscenter/api/session-usage.svelte')>();
  return { ...actual, sessionUsage: usageMocks.sessionUsage, releaseSessionUsage: usageMocks.releaseSessionUsage };
});

function usageResourceWithFiveHourPct(usedPct: number): Resource<SessionTokenUsage> {
  const data: SessionTokenUsage = {
    state: 'ok',
    family: 'claude',
    model: 'claude',
    model_display_name: 'Claude',
    model_cost_tier: null,
    effort: null,
    input_tokens: 100,
    output_tokens: 100,
    cache_read_input_tokens: null,
    cache_creation_input_tokens: null,
    total_tokens: 200,
    cost_estimate_usd: 0.01,
    context_used_tokens: 1000,
    context_window_tokens: 10000,
    context_remaining_pct: 90,
    as_of: new Date().toISOString(),
    detail: null,
    account: {
      id: 'acct_1',
      name: 'Test Account',
      short_name: null,
      provider: 'claude',
      plan: null,
      identity: null,
      credential_state: 'ok',
      fetched_at: new Date().toISOString(),
      next_poll_at: null,
      error: null,
      windows: [{ kind: 'five_hour', label: '5h', used_pct: usedPct, window_seconds: null, resets_at: null }],
      color: null,
      managed: false,
    },
  };
  return { status: 'ok', data, fetchedAt: Date.now(), error: null, refresh: async () => {}, stop: () => {} };
}

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;
const GLOBALS = ['SessionSidebar', 'SessionSidebarClicks'];

const ROWS: SidebarRow[] = [
  { name: 'cloude_a', session_id: 'ses_a', status: 'idle', agent_family: 'claude', project_id: 1, project_name: 'alpha', is_pinned: true },
  { name: 'cloude_b', session_id: 'ses_b', status: 'working', agent_family: 'claude', project_id: 1, project_name: 'alpha' },
  { name: 'cloude_c', session_id: 'ses_c', status: 'idle', agent_family: 'claude', project_id: null },
  { name: 'cloude_t', session_id: 'ses_t', agent_family: 'shell', kind: 'terminal', working_dir: '/tmp' },
];

function seedStores(): void {
  GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'crew', name: 'crew', position: 0, members: ['cloude_b'] }] });
  Store.save(['cloude_a'], []);
}

beforeEach(() => {
  document.body.innerHTML = '<div id="session-sidebar-list"></div><div id="rail"></div>';
  document.body.className = '';
  localStorage.clear();
  seedStores();
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  for (const key of GLOBALS) delete win[key];
  vi.restoreAllMocks();
});

function sections() {
  return buildRailSections({ rows: ROWS, host: rowHost(), open: () => {}, asleepLabel: 'asleep' });
}

test('each section with rows is one icon, in the drawer order; groups and projects branch per band', () => {
  const s = sections();
  expect(s.map((x) => x.id)).toEqual(['pinned', 'groups', 'projects', 'terminals']);
  expect(s.find((x) => x.id === 'pinned')!.nodes.map((n) => n.label)).toEqual(['cloude_a']);
  const groups = s.find((x) => x.id === 'groups')!.nodes;
  expect(groups.map((n) => n.label)).toEqual(['crew']);
  expect(groups[0]!.children!.map((n) => n.label)).toEqual(['cloude_b']);
  const projects = s.find((x) => x.id === 'projects')!.nodes;
  expect(projects.map((n) => n.label)).toEqual(['alpha', 'rogue agents']);
  expect(projects[0]!.children!.map((n) => n.label)).toEqual(['cloude_a', 'cloude_b']);
  expect(projects[0]!.children![1]!.agent?.status).toBe('working');
  expect(s.find((x) => x.id === 'terminals')!.nodes[0]!.agent).toBeUndefined();
});

test('the projects icon lists projects A-Z by name, rogue agents last, whatever order the rows arrive in', () => {
  const rows: SidebarRow[] = [
    { name: 'cloude_z', session_id: 'ses_z', status: 'idle', agent_family: 'claude', project_id: 3, project_name: 'zeta' },
    { name: 'cloude_r', session_id: 'ses_r', status: 'idle', agent_family: 'claude', project_id: null },
    { name: 'cloude_b', session_id: 'ses_b', status: 'idle', agent_family: 'claude', project_id: 2, project_name: 'Beta' },
    { name: 'cloude_a', session_id: 'ses_a', status: 'idle', agent_family: 'claude', project_id: 1, project_name: 'alpha' },
  ];
  const s = buildRailSections({ rows, host: rowHost(), open: () => {}, asleepLabel: 'asleep' });
  expect(s.find((x) => x.id === 'projects')!.nodes.map((n) => n.label)).toEqual(['alpha', 'Beta', 'zeta', 'rogue agents']);
});

function render(): HTMLElement {
  const target = document.getElementById('rail')!;
  mounted.push(mount(MiniRail, { target }));
  document.body.classList.add('session-sidebar-railed');
  flushSync();
  return target;
}

test('the claw opens the drawer through its own controller', async () => {
  const open = vi.fn();
  win.SessionSidebar = { _rows: [], open, refreshNow: () => undefined };
  const rail = render();
  (rail.querySelector('[data-rail="claw"]') as HTMLButtonElement).click();
  expect(open).toHaveBeenCalledTimes(1);
});

test('the usage bars each carry a short label', () => {
  win.SessionSidebar = { _rows: ROWS, open: () => {}, refreshNow: () => undefined };
  const rail = render();
  const labels = [...rail.querySelectorAll<HTMLElement>('.mr-usage-label')].map((el) => el.textContent?.trim());
  expect(labels).toEqual(['C', '5h', '7d']);
});

test('the 5h bar takes its colour from the shared scale, not a fixed hue: low is green, high is red', async () => {
  win.SessionSidebar = { _rows: ROWS, open: () => {}, refreshNow: () => undefined };
  win.TerminalController = { _sessionId: () => 'ses_a' };
  usageMocks.sessionUsage.mockReturnValue(usageResourceWithFiveHourPct(10));
  const railLow = render();
  const lowBar = railLow.querySelector<HTMLElement>('.mr-usage-bar[data-usage="5h"]')!;
  expect(lowBar.dataset.scale).toBe('1');
  await unmount(mounted.pop()!);

  usageMocks.sessionUsage.mockReturnValue(usageResourceWithFiveHourPct(95));
  const railHigh = render();
  const highBar = railHigh.querySelector<HTMLElement>('.mr-usage-bar[data-usage="5h"]')!;
  expect(highBar.dataset.scale).toBe('5');
  delete win.TerminalController;
});

test('the bars follow the terminal\'s bound primary session, not the URL or a row session_id', async () => {
  win.SessionSidebar = { _rows: ROWS, open: () => {}, refreshNow: () => undefined };
  history.pushState({}, '', '/');
  usageMocks.sessionUsage.mockReset();
  usageMocks.sessionUsage.mockReturnValue(usageResourceWithFiveHourPct(40));
  win.TerminalController = { _sessionId: () => 'adopted:cloude_x' };
  const rail = render();
  expect(usageMocks.sessionUsage).toHaveBeenCalledWith('adopted:cloude_x');
  const fill = rail.querySelector<HTMLElement>('.mr-usage-bar[data-usage="5h"] .oc-gauge__fill')!;
  expect(fill.style.width).toBe('40%');
  delete win.TerminalController;
});

test('a flyout row opens through activateRow: the painted row, else a stand-in', async () => {
  const activateRow = vi.fn(async (_ctl: unknown, _row: Element) => {});
  win.SessionSidebar = { _rows: ROWS, open: () => {}, refreshNow: () => undefined };
  win.SessionSidebarClicks = { activateRow };
  document.getElementById('session-sidebar-list')!.innerHTML =
    '<div class="session-sidebar-row" data-name="cloude_a" data-session-id="ses_a"></div>';
  sidebarTabs.stored = 'agents';
  const rail = render();

  (rail.querySelector('[data-rail-section="pinned"]') as HTMLButtonElement).click();
  flushSync();
  (document.querySelector('[role="menuitem"]') as HTMLElement).click();
  expect(activateRow).toHaveBeenCalledTimes(1);
  expect(activateRow.mock.calls[0]![1]).toBe(document.querySelector('#session-sidebar-list [data-name="cloude_a"]'));
  flushSync();
  expect(document.querySelector('[role="menu"]'), 'the flyout closes on a pick').toBeNull();

  (rail.querySelector('[data-rail-section="terminals"]') as HTMLButtonElement).click();
  flushSync();
  (document.querySelector('[role="menuitem"]') as HTMLElement).click();
  const standIn = activateRow.mock.calls[1]![1] as HTMLElement;
  expect(standIn.isConnected).toBe(false);
  expect(standIn.dataset.name).toBe('cloude_t');
  expect(standIn.dataset.sessionId).toBe('ses_t');
});

test('a plugin page section is one rail icon with the plugin\'s declared glyph and label, in the review slot', async () => {
  const { registerPageSections, resetPageSections } = await import('../drawer/page-sections');
  resetPageSections();
  registerPageSections([{ id: 'review', labelKey: 'cplug.reviewboard.page_section', icon: 'eye' }]);
  try {
    const page = { name: 'browser:0123456789abcdef', kind: 'browser', browser_id: '0123456789abcdef', page: true, section: 'review', label: 'bottom bar', status: 'page' };
    const sections = buildRailSections({ rows: [...ROWS, page as unknown as SidebarRow], host: rowHost(), open: () => {}, asleepLabel: 'asleep' });
    const section = sections.find((s) => s.id === 'review');
    expect(section).toMatchObject({ glyph: 'eye', labelKey: 'cplug.reviewboard.page_section' });
    expect(section!.nodes.map((n) => n.label)).toEqual(['bottom bar']);
    expect(sections.find((s) => s.id === 'browsers')?.nodes.some((n) => n.label === 'bottom bar') ?? false).toBe(false);
  } finally {
    resetPageSections();
  }
});


describe('the rail keys', () => {
  beforeEach(() => {
    registerCoreSidebarWidgets();
    approvals.items = [];
    win.SessionSidebar = { _rows: ROWS, open: vi.fn(), refreshNow: () => undefined };
  });
  afterEach(() => {
    closeFlyout();
      approvals.items = [];
  });

  const keysOf = (rail: HTMLElement): (string | undefined)[] => [...rail.querySelectorAll<HTMLElement>('[data-zone-item]')].map((b) => b.dataset.zoneItem);

  test('one rail, not two: the keys are the sidebar rail\'s, the classic Menu and Agents tabs are not drawn', () => {
    const rail = render();
    expect(rail.querySelector('[data-rail-tab]')).toBeNull();
    expect(keysOf(rail)).toEqual([MENU_FLYOUT, SESSION_LIST_WIDGET]);
    for (const key of rail.querySelectorAll<HTMLElement>('[data-zone-item]')) {
      expect(key.textContent?.trim(), 'icon only').toBe('');
      expect(key.getAttribute('aria-label')).toBeTruthy();
    }
    expect(rail.querySelector('[data-rail-item]'), 'the menu\'s destinations live in its slide-out').toBeNull();
    expect([...rail.querySelectorAll<HTMLElement>('[data-rail-section]')].length, 'the agents sections stay').toBeGreaterThan(0);
  });

  test('every key opens the drawer and its slide-out: menu opens the menu, agents closes any slide-out', () => {
    const rail = render();
    const key = (id: string): HTMLButtonElement => rail.querySelector<HTMLButtonElement>(`[data-zone-item="${id}"]`)!;
    key(MENU_FLYOUT).click();
    flushSync();
    expect(win.SessionSidebar && (win.SessionSidebar as { open: ReturnType<typeof vi.fn> }).open).toHaveBeenCalledTimes(1);
    expect(activeFlyout()).toBe(MENU_FLYOUT);
    key(SESSION_LIST_WIDGET).click();
    flushSync();
    expect((win.SessionSidebar as { open: ReturnType<typeof vi.fn> }).open).toHaveBeenCalledTimes(2);
    expect(activeFlyout()).toBeNull();
  });

  test('a question shows its key with the waiting count and the arrival cue; the key opens the questions slide-out', async () => {
    const rail = render();
    approvals.items = [{ id: 'q1', session_id: 's1', title: 'deploy?', created_at: new Date().toISOString() } as never];
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
    expect(keysOf(rail)).toContain(QUESTIONS_FLYOUT);
    const key = rail.querySelector<HTMLButtonElement>(`[data-zone-item="${QUESTIONS_FLYOUT}"]`)!;
    expect(key.querySelector('[data-rail-badge]')?.textContent).toBe('1');
    expect(key.querySelector<HTMLElement>('[data-rail-badge]')?.dataset.cue, 'the badge pulses, the one arrival cue').toBe('on');
    key.click();
    flushSync();
    expect(activeFlyout()).toBe(QUESTIONS_FLYOUT);
  });

  test('keyboard: one tab stop, the arrows and Home/End walk the keys top to bottom', () => {
    const rail = render();
    const keys = [...rail.querySelectorAll<HTMLButtonElement>('[data-zone-item]')];
    expect(keys.filter((k) => k.tabIndex === 0)).toHaveLength(1);
    keys[0]!.focus();
    keys[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    flushSync();
    expect(document.activeElement).toBe(keys[1]);
    keys[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }));
    flushSync();
    expect(document.activeElement).toBe(keys[0]);
    keys[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
    flushSync();
    expect(document.activeElement).toBe(keys[keys.length - 1]);
  });
});

describe('the mini rail right-click menu', () => {
  function rightClick(el: Element): boolean {
    return el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 12, clientY: 40 }));
  }
  const labels = (): string[] => [...document.querySelectorAll('.acm-menu .acm-item')].map((b) => b.textContent ?? '');

  test('opens at the pointer with open the drawer first and no pin item; the drawer item opens the drawer', () => {
    const open = vi.fn();
    win.SessionSidebar = { _rows: [], open, refreshNow: () => undefined };
    const rail = render();
    expect(rightClick(rail.querySelector('.mr')!), 'the browser menu is prevented').toBe(false);
    flushSync();
    expect(document.querySelector('.acm-menu')).not.toBeNull();
    expect(labels()[0]).toContain('open the drawer');
    expect(labels().join('|'), 'no rail has a pin item').not.toContain('pin rail');
    (document.querySelector('.acm-menu .acm-item') as HTMLButtonElement).click();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

test('a settings button sits above the bottom cluster and carries the menu\'s settings label', () => {
  win.SessionSidebar = { _rows: ROWS, open: () => {}, refreshNow: () => undefined };
  const rail = render();
  const btn = rail.querySelector<HTMLButtonElement>('.mr-settings [data-rail-settings]');
  expect(btn, 'the settings button').not.toBeNull();
  expect(btn!.getAttribute('aria-label')).toBe('settings');
  expect(btn!.nextElementSibling ?? btn!.parentElement!.nextElementSibling!.classList.contains('mr-footer')).toBeTruthy();
});
