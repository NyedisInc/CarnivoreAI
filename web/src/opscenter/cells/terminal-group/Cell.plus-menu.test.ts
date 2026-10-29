/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups, tabsFor } from '../../engine/tab-groups.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
const flows = vi.hoisted(() => ({ started: [] as string[], resolve: null as null | (() => void) }));
vi.mock('../../api/host', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/host')>();
  return {
    ...actual,
    startNewSession: (kind: string) => {
      flows.started.push(kind);
      const nav = (globalThis as unknown as { NavigationGeneration: { begin(t: string): number } }).NavigationGeneration.begin(kind);
      return new Promise<void>((resolve) => {
        flows.resolve = () => {
          globalThis.dispatchEvent(new CustomEvent('session-created', { detail: { session: { id: 'ses_new' }, nav } }));
          resolve();
        };
      });
    },
  };
});
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
      data: [row('ses_a', 'alpha', 'claude'), row('ses_b', 'beta', 'shell'), { ...row('ses_c', 'gamma', 'claude'), project_id: 7, project_name: 'api' }],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  let generation = 0;
  (globalThis as unknown as { NavigationGeneration: unknown }).NavigationGeneration = {
    begin: () => ++generation, current: () => generation,
    keep: (token: number) => token === generation, isCurrent: (token: number) => token === generation,
  };
  flows.started.length = 0;
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  inputFocus.forget(B);
  inputFocus.forget(C);
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


function openMenu(root: HTMLElement): HTMLButtonElement {
  const plus = root.querySelector('.oc-tab-new') as HTMLButtonElement;
  plus.click();
  flushSync();
  return plus;
}

function item(id: string): HTMLButtonElement {
  return document.querySelector(`[role="menuitem"][data-node="${id}"]`) as HTMLButtonElement;
}

function openBranch(id: string): void {
  item(id).click();
  flushSync();
}

test('the dimmed + follows the tablist and opens agent / terminal / browser', () => {
  const root = draw();
  const plus = root.querySelector('.oc-tab-new') as HTMLButtonElement;
  expect(plus).not.toBeNull();
  expect(plus.closest('[role="tablist"]')).toBeNull();
  expect(plus.previousElementSibling?.getAttribute('role')).toBe('tablist');
  expect(plus.getAttribute('aria-expanded')).toBe('false');
  openMenu(root);
  expect(plus.getAttribute('aria-expanded')).toBe('true');
  const top = [...document.querySelectorAll('[role="menu"][data-level="0"] [role="menuitem"]')].map((el) => (el as HTMLElement).dataset.node);
  expect(top).toEqual(['agent', 'terminal', 'blueprint', 'browser', 'widget']);
  expect(item('browser').getAttribute('aria-disabled')).toBeNull();
  openBranch('agent');
  const agent = [...document.querySelectorAll('[role="menu"][data-level="1"] [role="menuitem"]')].map((el) => (el as HTMLElement).dataset.node);
  expect(agent).toEqual(['agent/new', 'agent/p:7']);
  expect(item('agent/new').classList.contains('acm-sep')).toBe(false);
  expect(item('agent/p:7').classList.contains('acm-sep')).toBe(true);
});

test('picking a session opens it as a tab here and shows it', () => {
  const before = JSON.stringify(terminalLayout.state.layout);
  const root = draw();
  openMenu(root);
  openBranch('agent');
  openBranch('agent/p:7');
  expect(item('agent/p:7/ses_c').querySelector('.acm-label')?.textContent?.trim()).toBe('gamma');
  item('agent/p:7/ses_c').click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A, C]);
  expect(root.querySelector(`[data-tab="${C}"]`)?.getAttribute('aria-selected')).toBe('true');
  expect(inputFocus.selected).toBe(C);
  expect(document.querySelector('.acm-menu')).toBeNull();
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
});

test('a session already open as a tab here, and an emptied project, are both absent from the menu', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, C] } });
  const root = draw();
  openMenu(root);
  openBranch('agent');
  const agent = [...document.querySelectorAll('[role="menu"][data-level="1"] [role="menuitem"]')].map((el) => (el as HTMLElement).dataset.node);
  expect(agent).toEqual(['agent/new']);
  expect(item('agent/p:7')).toBeNull();
  expect(tabsFor(terminalLayout, A)).toEqual([A, C]);
});

test('the browser root opens a branch with a new proxy browser and starts no session flow', () => {
  const root = draw();
  openMenu(root);
  openBranch('browser');
  expect(item('browser/new')).not.toBeNull();
  expect(document.querySelector('.acm-menu')).not.toBeNull();
  expect(flows.started).toEqual([]);
});

for (const [node, kind] of [['terminal', 'terminal'], ['agent/new', 'agent']] as const) {
  test(`${node} runs the drawer's ${kind} flow and lands the created session as a tab here`, async () => {
    const navigated = vi.fn();
    const appJs = (event: Event): void => {
      const nav = (event as CustomEvent<{ nav?: number }>).detail?.nav;
      if (nav === (globalThis as unknown as { NavigationGeneration: { current(): number } }).NavigationGeneration.current()) navigated();
    };
    globalThis.addEventListener('session-created', appJs);
    try {
      const root = draw();
      openMenu(root);
      if (node === 'agent/new') openBranch('agent');
      item(node).click();
      flushSync();
      expect(flows.started).toEqual([kind]);
      flows.resolve?.();
      await Promise.resolve();
      flushSync();
      expect(tabsFor(terminalLayout, A)).toEqual([A, 'terminal:ses_new']);
      expect(root.querySelector('[data-tab="terminal:ses_new"]')?.getAttribute('aria-selected')).toBe('true');
      expect(navigated).not.toHaveBeenCalled();
    } finally {
      globalThis.removeEventListener('session-created', appJs);
      inputFocus.forget('terminal:ses_new');
    }
  });
}
