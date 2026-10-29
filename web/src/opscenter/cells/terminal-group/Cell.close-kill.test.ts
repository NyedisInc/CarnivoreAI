/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups, tabsFor } from '../../engine/tab-groups.svelte';
import { layoutMode } from '../../layouts/mode.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import { LONG_PRESS_MS } from '../../shell/TabStrip.svelte';
import type { SlotId } from '../../engine/types';

const clients = vi.hoisted(() => ({ made: [] as Array<{ id: string; _tabHidden?: boolean }> }));
vi.mock('../terminal-live/client', () => ({
  startLiveTerminal: (_el: unknown, instance: string) => {
    // A class instance, like the real client: Svelte never proxies one.
    const client = new (class FakeClient { constructor(public id: string) {} })(instance);
    clients.made.push(client);
    return { client, dispose() {} };
  },
}));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string, label: string, pin: string | null) => ({
    session: { id }, label, agent_family: 'shell', tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: pin,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_a', 'alpha', null), row('ses_b', 'beta', 'dracula')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
let app: ReturnType<typeof mount> | null = null;
const api = { destroySession: vi.fn(async () => ({})), destroyExternalSession: vi.fn(async () => ({})) };
let confirmAnswer = false;
const confirmCalls: Array<[string, string]> = [];
const tabHidden: Array<[unknown, boolean]> = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  terminalLayout.add('terminal', 'ses_a');
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  api.destroySession.mockClear();
  api.destroyExternalSession.mockClear();
  confirmCalls.length = 0;
  tabHidden.length = 0;
  clients.made.length = 0;
  const w = globalThis as Record<string, unknown>;
  w.API = api;
  w.SessionRowActions = {
    ACTION_CLOSE: 'close', ACTION_REMOVE: 'remove', ACTION_RESTART: 'restart',
    actionsFor: () => ['close'], labelFor: (a: string) => a, requiresConfirm: () => true,
    confirm: async (action: string, name: string) => {
      confirmCalls.push([action, name]);
      return confirmAnswer;
    },
  };
  w.CloudeWeb = { launchpad: { loadRunningSessions: async () => {} } };
  w.Themes = {
    getSessionManifest: ({ pinnedTheme }: { pinnedTheme: string | null }) => ({
      id: pinnedTheme ?? 'global', cssVars: { '--color-accent': pinnedTheme ? '#bd93f9' : '#ff8800' },
    }),
    onXtermThemeChange: () => () => {},
  };
  w.TerminalSizeVote = {
    setTabHidden: (client: { _tabHidden?: boolean }, hidden: boolean) => {
      if (!!client._tabHidden === hidden) return;
      client._tabHidden = hidden;
      tabHidden.push([client, hidden]);
    },
  };
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  inputFocus.forget(B);
  terminalLayout.remove(A);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
  window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
  for (const key of ['API', 'SessionRowActions', 'CloudeWeb', 'Themes', 'TerminalSizeVote']) {
    delete (globalThis as Record<string, unknown>)[key];
  }
});

function draw(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();
  return target;
}

function closer(root: HTMLElement, tab: string): HTMLButtonElement {
  return root.querySelector(`[data-tab-close="${tab}"]`) as HTMLButtonElement;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) await tick();
  flushSync();
}

test('the x closes the tab only: no kill, the session is untouched, the component stays', () => {
  const root = draw();
  expect(closer(root, B).dataset.tabAction).toBe('close');
  closer(root, B).click();
  flushSync();
  expect(root.querySelector(`[data-tab="${B}"]`)).toBeNull();
  expect(tabsFor(terminalLayout, A)).toEqual([A]);
  expect(api.destroySession).not.toHaveBeenCalled();
  expect(confirmCalls).toHaveLength(0);
  expect(terminalLayout.state.layout.rows.some((row) => row.slots.some((s) => s.id === A))).toBe(true);
});

test('closing the showing tab shows its neighbour', () => {
  const root = draw();
  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).click();
  flushSync();
  closer(root, B).click();
  flushSync();
  expect(root.querySelector(`[data-tab="${A}"]`)?.getAttribute('aria-selected')).toBe('true');
});

test('closing the last tab takes the component off the grid', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A] } });
  const root = draw();
  closer(root, A).click();
  flushSync();
  expect(terminalLayout.state.layout.rows.some((row) => row.slots.some((s) => s.id === A))).toBe(false);
  expect(api.destroySession).not.toHaveBeenCalled();
});

test('holding Shift turns every x into the skull, and letting go turns it back', () => {
  const root = draw();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
  flushSync();
  expect(closer(root, A).dataset.tabAction).toBe('kill');
  expect(closer(root, B).dataset.tabAction).toBe('kill');
  expect(closer(root, B).querySelector('[data-icon="skull"]')).not.toBeNull();
  window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
  flushSync();
  expect(closer(root, B).dataset.tabAction).toBe('close');
});

test('skull then cancel: the one kill path confirms, nothing is killed, the tab stays', async () => {
  confirmAnswer = false;
  const root = draw();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
  flushSync();
  closer(root, B).click();
  await settle();
  expect(confirmCalls).toEqual([['close', 'beta']]);
  expect(api.destroySession).not.toHaveBeenCalled();
  expect(tabsFor(terminalLayout, A)).toEqual([A, B]);
});

test('skull then confirm: the session is killed by id, then its tab closes', async () => {
  confirmAnswer = true;
  const root = draw();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
  flushSync();
  closer(root, B).click();
  await settle();
  expect(api.destroySession).toHaveBeenCalledWith('ses_b');
  expect(tabsFor(terminalLayout, A)).toEqual([A]);
});

test('skull then confirm on a layout page: the tab closes too, no dead session-ended tab is left (#2509)', async () => {
  confirmAnswer = true;
  layoutMode.uuid = 'lay_test';
  try {
    const root = draw();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
    flushSync();
    closer(root, B).click();
    await settle();
    expect(api.destroySession).toHaveBeenCalledWith('ses_b');
    expect(tabsFor(terminalLayout, A)).toEqual([A]);
  } finally {
    layoutMode.uuid = '';
  }
});

test('a long-press arms the skull and runs nothing until the skull is tapped', async () => {
  vi.useFakeTimers();
  try {
    confirmAnswer = false;
    const root = draw();
    const x = closer(root, B);
    x.dispatchEvent(new PointerEvent('pointerdown', { pointerType: 'touch', bubbles: true }));
    vi.advanceTimersByTime(LONG_PRESS_MS + 10);
    flushSync();
    expect(closer(root, B).dataset.tabAction).toBe('kill');
    closer(root, B).click();
    flushSync();
    expect(confirmCalls).toHaveLength(0);
    expect(tabsFor(terminalLayout, A)).toEqual([A, B]);
    closer(root, B).click();
    vi.useRealTimers();
    await settle();
    expect(confirmCalls).toEqual([['close', 'beta']]);
  } finally {
    vi.useRealTimers();
  }
});

test('a hidden tab withdraws its size vote; showing it rejoins', () => {
  const root = draw();
  const clientB = clients.made.find((c) => c.id === B);
  const clientA = clients.made.find((c) => c.id === A);
  expect(clientB?._tabHidden).toBe(true);
  expect(clientA?._tabHidden ?? false).toBe(false);
  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(clientB?._tabHidden).toBe(false);
  expect(clientA?._tabHidden).toBe(true);
  expect(inputFocus.owner).toBe(B);
});

test('an inactive tab is tinted with its session theme accent; the showing tab is not', () => {
  const root = draw();
  const wrapB = root.querySelector(`[data-tab="${B}"]`)?.parentElement as HTMLElement;
  const wrapA = root.querySelector(`[data-tab="${A}"]`)?.parentElement as HTMLElement;
  expect(wrapB.classList.contains('oc-tabwrap-tinted')).toBe(true);
  expect(wrapB.style.getPropertyValue('--oc-tab-tint')).toBe('#bd93f9');
  expect(wrapA.classList.contains('oc-tabwrap-tinted')).toBe(false);
  expect(wrapA.style.getPropertyValue('--oc-tab-tint')).toBe('#ff8800');
});

test('every tab pane is its own theme scope', () => {
  const root = draw();
  const panes = root.querySelectorAll('[data-tab-pane]');
  expect(panes).toHaveLength(2);
  panes.forEach((pane) => expect(pane.hasAttribute('data-theme-scope')).toBe(true));
});
