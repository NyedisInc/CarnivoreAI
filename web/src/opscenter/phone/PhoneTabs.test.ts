/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PhoneTabs from './PhoneTabs.svelte';
import PhoneTabPane from './PhoneTabPane.svelte';
import { terminalLayout } from '../engine/layout.svelte';
import { activeTabFor, resetTabCache, setGroups } from '../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const started: Array<{ slot: string; disposed: boolean }> = [];
vi.mock('../cells/terminal-live/client', () => ({
  startLiveTerminal: (_host: HTMLElement, slot: string) => {
    const handle = { slot, disposed: false };
    started.push(handle);
    return { client: {}, dispose: () => (handle.disposed = true) };
  },
}));
vi.mock('../cells/terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
const navigate = vi.fn();
vi.mock('../api/host', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/host')>()),
  openSession: (...args: unknown[]) => navigate(...args),
  primarySessionId: () => 'ses_a',
}));
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  const row = (id: string, label: string) => ({
    session: { id }, label, agent_family: 'claude', tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_a', 'alpha'), row('ses_b', 'beta'), row('ses_c', 'gamma')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';
const votes: Array<{ client: unknown; hidden: boolean }> = [];
const PAGE = { page: true };
const apps: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  (globalThis as Record<string, unknown>).TerminalController = PAGE;
  (globalThis as Record<string, unknown>).TerminalSizeVote = {
    setTabHidden: (client: unknown, hidden: boolean) => votes.push({ client, hidden }),
  };
  terminalLayout.bindSession('cloude_ses_a', 1);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, C] } });
});

afterEach(async () => {
  for (const app of apps.splice(0)) await unmount(app);
  terminalLayout.bindSession('');
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
  started.length = 0;
  votes.length = 0;
  navigate.mockReset();
});

function draw(component: typeof PhoneTabs | typeof PhoneTabPane): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(component, { target }));
  flushSync();
  return target;
}

test('the strip draws the page component\'s tabs at touch size, with the "+" and no drag', () => {
  const root = draw(PhoneTabs);
  const row = root.querySelector('.oc-tabrow') as HTMLElement;
  expect(row.classList.contains('oc-tabrow-touch')).toBe(true);
  const tabs = [...root.querySelectorAll<HTMLElement>('[role="tab"]')].map((tab) => tab.textContent?.trim());
  expect(tabs).toEqual(['alpha', 'beta', 'gamma']);
  expect(root.querySelectorAll('.oc-tab-x')).toHaveLength(3);
  const plus = root.querySelector('.oc-tab-new') as HTMLButtonElement;
  plus.click();
  flushSync();
  expect(plus.getAttribute('aria-expanded')).toBe('true');
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
});

test('a tap switches the view: no navigation, one live client, the page pane stops voting', () => {
  const strip = draw(PhoneTabs);
  const pane = draw(PhoneTabPane);
  expect(pane.querySelector('[data-phone-tab-pane]')).toBeNull();
  (strip.querySelector(`[data-tab="${B}"]`) as HTMLElement).click();
  flushSync();
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(B);
  expect(navigate).not.toHaveBeenCalled();
  expect(pane.querySelector('[data-phone-tab-pane]')?.getAttribute('data-phone-tab-pane')).toBe(B);
  expect(started.map((s) => s.slot)).toEqual([B]);
  expect(votes.at(-1)).toEqual({ client: PAGE, hidden: true });

  (strip.querySelector(`[data-tab="${C}"]`) as HTMLElement).click();
  flushSync();
  expect(started.map((s) => [s.slot, s.disposed])).toEqual([[B, true], [C, false]]);

  (strip.querySelector(`[data-tab="${PRIMARY_SLOT}"]`) as HTMLElement).click();
  flushSync();
  expect(started.every((s) => s.disposed)).toBe(true);
  expect(pane.querySelector('[data-phone-tab-pane]')).toBeNull();
  expect(votes.at(-1)).toEqual({ client: PAGE, hidden: false });
});

test('the strip is the phone top bar: claw first (opens the drawer), tabs scroll between, bell and bare kebab last', () => {
  const toggle = vi.fn();
  (globalThis as Record<string, unknown>).SessionSidebar = { toggle };
  const menuToggle = document.createElement('button');
  menuToggle.id = 'header-menu-toggle';
  const pressed = vi.fn();
  menuToggle.addEventListener('click', pressed);
  document.body.appendChild(menuToggle);

  const root = draw(PhoneTabs);
  const bar = root.querySelector('[data-phone-tabs]') as HTMLElement;
  const order = [...bar.children].map((el) => el.getAttribute('data-phone-tabs-claw') !== null ? 'claw' : el.hasAttribute('data-phone-tabs-scroll') ? 'tabs' : el.hasAttribute('data-phone-tabs-end') ? 'end' : '?');
  expect(order).toEqual(['claw', 'tabs', 'end']);

  const claw = bar.querySelector('[data-phone-tabs-claw]') as HTMLButtonElement;
  expect(claw.getAttribute('aria-label')).toBe('open the agents drawer');
  claw.click();
  expect(toggle).toHaveBeenCalledTimes(1);

  const end = bar.querySelector('[data-phone-tabs-end]') as HTMLElement;
  const kebab = end.querySelector('[data-phone-tabs-kebab]') as HTMLButtonElement;
  expect(kebab.className).toContain('tw:border-0');
  expect(kebab.getAttribute('aria-label')).toBe('more actions');
  kebab.click();
  expect(pressed).toHaveBeenCalledTimes(1);
  delete (globalThis as Record<string, unknown>).SessionSidebar;
});
