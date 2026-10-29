/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups } from '../../engine/tab-groups.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

// The corner menu this frame opens is promoted into the top layer (issue
// #860); jsdom has neither method.
installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string, label: string, family: string) => ({
    session: { id }, label, agent_family: family, tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_a', 'alpha', 'claude'), row('ses_b', 'beta', 'shell')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
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
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  inputFocus.forget(B);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
});

function draw(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();
  return target;
}

test('a one-tab component: strip above the title row, no separate corner button, name and status light move to the tab', () => {
  const root = draw();
  const strip = root.querySelector('.oc-frame-strip') as HTMLElement;
  expect(strip).not.toBeNull();
  expect(root.querySelector('.oc-frame-title')).toBeNull();
  const tabs = strip.querySelectorAll('[role="tab"]');
  expect(tabs).toHaveLength(1);
  expect(tabs[0]?.textContent?.trim()).toBe('alpha');
  expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
  expect(root.querySelector('h2.oc-tl-name')).toBeNull();
  expect(root.querySelector('.oc-tl-dot')).toBeNull();
  expect(strip.querySelector('.oc-tl-controls')).not.toBeNull();
  expect(root.querySelectorAll('[data-corner]')).toHaveLength(1);
  expect(strip.querySelector('[data-corner]')).not.toBeNull();
  expect(root.querySelector('.oc-frame-title [data-corner]')).toBeNull();
});

test('the tab icon opens the same component menu the old corner button did (#514 follow-up)', () => {
  const root = draw();
  const icon = root.querySelector('[data-tab="terminal:ses_a"]')
    ?.parentElement?.querySelector('.oc-tab-icon--action') as HTMLButtonElement;
  expect(icon).not.toBeNull();
  expect(icon.getAttribute('aria-haspopup')).toBe('menu');
  expect(icon.getAttribute('aria-label')).toBe('terminal options');
  expect(document.querySelector('.acm-menu[role="menu"]')).toBeNull();

  icon.click();
  flushSync();
  const menu = document.querySelector('.acm-menu[role="menu"]');
  expect(menu).not.toBeNull();
  expect(menu?.getAttribute('aria-label')).toBe('ses_a options');
  expect(icon.getAttribute('aria-expanded')).toBe('true');

  icon.click();
  flushSync();
  expect(document.querySelector('.acm-menu[role="menu"]')).toBeNull();
  expect(icon.getAttribute('aria-expanded')).toBe('false');
});

test('two tabs: both mounted, only the active one visible and reachable; a click swaps the view, not the grid', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  const before = JSON.stringify(terminalLayout.state.layout);
  const root = draw();
  const paneA = root.querySelector(`[data-tab-pane="${A}"]`) as HTMLElement;
  const paneB = root.querySelector(`[data-tab-pane="${B}"]`) as HTMLElement;
  expect(paneA.inert).toBe(false);
  expect(paneB.inert).toBe(true);
  expect(paneB.getAttribute('aria-hidden')).toBe('true');
  expect(paneB.classList.contains('oc-tabpane-hidden')).toBe(true);
  expect(root.querySelector('.oc-frame-title')).toBeNull();

  (root.querySelector(`[data-tab="${B}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(paneA.inert).toBe(true);
  expect(paneB.inert).toBe(false);
  expect(root.querySelector(`[data-tab="${B}"]`)?.getAttribute('aria-selected')).toBe('true');
  expect(root.querySelector('.oc-frame-title')).toBeNull();
  expect(inputFocus.selected).toBe(B);
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
});

test('arrow keys move between tabs and select as they go', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  const root = draw();
  const first = root.querySelector(`[data-tab="${A}"]`) as HTMLButtonElement;
  first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  flushSync();
  expect(root.querySelector(`[data-tab="${B}"]`)?.getAttribute('aria-selected')).toBe('true');
  expect(root.querySelector(`[data-tab="${B}"]`)?.getAttribute('tabindex')).toBe('0');
});

test('a tab reads component icon (the coloured provider mark when it has a provider), status light (agents only), name, x (#514, #623)', () => {
  (globalThis as { AgentFamilyIcon?: unknown }).AgentFamilyIcon = {
    normalize: (f: string | null) => (f === 'claude' || f === 'shell' ? f : 'unknown'),
    svg: (f: string | null) => `<svg data-family="${f}"></svg>`,
  };
  try {
    setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
    const root = draw();
    const wrapOf = (tab: string) => root.querySelector(`[data-tab="${tab}"]`)?.parentElement as HTMLElement;
    const parts = (tab: string) => [...wrapOf(tab).querySelectorAll('.oc-tab-icon, .status-led, .oc-tab-name, .oc-tab-x')]
      .map((el) => (el.classList.contains('status-led') ? 'led'
        : el.classList.contains('oc-tab-icon') ? 'icon'
            : el.classList.contains('oc-tab-name') ? 'name' : 'x'));
    expect(parts(A)).toEqual(['icon', 'led', 'name', 'x']);
    expect(wrapOf(A).querySelector('.oc-tab-mark svg')?.getAttribute('data-family')).toBe('claude');
    expect(parts(B)).toEqual(['icon', 'name', 'x']);
    expect(wrapOf(A).querySelector('.status-led')?.classList.contains('status-dot--idle')).toBe(true);
  } finally {
    delete (globalThis as { AgentFamilyIcon?: unknown }).AgentFamilyIcon;
  }
});
