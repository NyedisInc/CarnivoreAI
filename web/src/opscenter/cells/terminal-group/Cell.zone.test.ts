/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups } from '../../engine/tab-groups.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const menus = vi.hoisted(() => ({ openRowMenu: vi.fn(() => true), openBrowserItemMenu: vi.fn(() => true) }));
vi.mock('../terminal-live/row-menu', () => ({ ...menus, uuidOfTmuxName: () => 'uuid' }));
vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string, label: string) => ({
    session: { id }, label, agent_family: 'claude', tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: { data: [row('ses_a', 'alpha'), row('ses_b', 'beta')], status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {} },
  };
});

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  menus.openRowMenu.mockClear();
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  inputFocus.forget(B);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
  vi.unstubAllGlobals();
});

function draw(): HTMLElement {
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();
  return target;
}

const stripTools = (root: HTMLElement): string[] =>
  [...root.querySelectorAll('.oc-frame-strip .oc-terminal-utilities')].map((el) => el.getAttribute('data-session-id') ?? '');

test('the strip row tools are the active tab\'s and switch with it', () => {
  const root = draw();
  expect(stripTools(root)).toEqual(['ses_a']);
  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(stripTools(root)).toEqual(['ses_b']);
});

test('a right-click on the inactive tab opens that tab\'s menu', () => {
  const root = draw();
  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).dispatchEvent(
    new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 30, clientY: 10 }),
  );
  flushSync();
  expect(menus.openRowMenu).toHaveBeenCalledTimes(1);
  const calls = menus.openRowMenu.mock.calls as unknown as [{ session?: { id: string } }][];
  expect(calls[0]![0].session?.id).toBe('ses_b');
  expect(root.querySelector(`[data-tab="${A}"]`)?.getAttribute('aria-selected')).toBe('true');
});

test('switching the active tab writes nothing: no request, no layout change', () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
  const root = draw();
  const before = JSON.stringify(terminalLayout.state.layout);
  fetchSpy.mockClear();
  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).click();
  flushSync();
  const writes = fetchSpy.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method && (init as RequestInit).method !== 'GET');
  expect(writes).toEqual([]);
  expect(fetchSpy.mock.calls.map(([url]) => String(url)).filter((url) => url.includes('ui-preferences'))).toEqual([]);
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
});
