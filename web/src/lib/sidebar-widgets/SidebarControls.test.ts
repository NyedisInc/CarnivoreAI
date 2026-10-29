/** @vitest-environment jsdom */
import * as Density from '../drawer/density';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SidebarControls from './SidebarControls.svelte';
import { drawerSurface } from '../drawer-tabs/drawer-surface.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const REPO = path.resolve(process.cwd(), '..');

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
  return source.slice(start, end + '</aside>'.length);
}

function installDensity(): void {
  Density.init();
  win.SessionSidebarDensity = {
    init: Density.init, apply: Density.apply, setMode: Density.setMode, currentMode: Density.currentMode,
  };
}

const mounted: ReturnType<typeof mount>[] = [];
const win = globalThis as unknown as Record<string, unknown>;

beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  localStorage.clear();
  drawerSurface.page = 'home';
  cplugEnablement.enabled = { huddle: false };
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(async () => {
  cplugEnablement.enabled = {};
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  for (const key of ['CloudeWeb', 'SessionSidebar', 'SessionSidebarDensity']) delete win[key];
  vi.restoreAllMocks();
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.querySelector('.session-sidebar-header')!.append(target);
  mounted.push(mount(SidebarControls, { target }));
  flushSync();
  return target;
}

const actionsOf = (row: HTMLElement) =>
  [...row.querySelectorAll<HTMLElement>('[role="toolbar"] [data-action]')].map((b) => b.dataset.action);

test('the view menu, then the "+", each named; only the view menu keeps a tip', () => {
  const row = render();
  expect(actionsOf(row)).toEqual(['density', 'new-session']);
  expect(row.querySelector('[data-action="add-component"]')).toBeNull();
  expect(row.querySelector('[data-action="import-project"]'), 'import lives in the "+" menu').toBeNull();
  for (const btn of row.querySelectorAll<HTMLElement>('[data-action]')) {
    expect(btn.getAttribute('aria-label'), `${btn.dataset.action} has no name`).toBeTruthy();
    if (btn.dataset.action === 'new-session') expect(btn.getAttribute('title')).toBeNull();
    else expect(btn.getAttribute('title'), `${btn.dataset.action} has no tooltip`).toBeTruthy();
    expect(btn.getAttribute('aria-label')).not.toMatch(/^drawer\./);
  }
});

test('"+" project opens the full new-project menu; the import button is gone', () => {
  const startNewClaudeProject = vi.fn(async () => {});
  win.CloudeWeb = { launchpad: { startNewClaudeProject } };
  const row = render();
  expect(row.querySelector('[data-action="import-project"]')).toBeNull();
  const plus = row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!;
  plus.click();
  flushSync();
  const project = row.querySelector<HTMLButtonElement>('[data-node="project"]')!;
  expect(project.classList.contains('acm-sep'), 'project and group sit apart from the session kinds').toBe(true);
  project.click();
  flushSync();
  expect(startNewClaudeProject).toHaveBeenCalledTimes(1);
  expect(row.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(plus);
});

test('"+" group runs the drawer\'s own new group flow, filing no session', () => {
  const createGroupThenAssign = vi.fn(async () => {});
  win.SessionSidebarGroupActions = { createGroupThenAssign };
  try {
    const row = render();
    row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!.click();
    flushSync();
    row.querySelector<HTMLButtonElement>('[data-node="group"]')!.click();
    flushSync();
    expect(createGroupThenAssign).toHaveBeenCalledTimes(1);
    expect(createGroupThenAssign).toHaveBeenCalledWith(null);
    expect(row.querySelector('[role="menu"]')).toBeNull();
  } finally {
    delete win.SessionSidebarGroupActions;
  }
});

test('"+" opens a submenu: agent runs the plain create flow, terminal opens a shell in ~', () => {
  const createNewSession = vi.fn(async () => {});
  const createConsoleSession = vi.fn(async () => {});
  win.CloudeWeb = { launchpad: { createNewSession, createConsoleSession } };
  const row = render();
  const plus = row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!;
  expect(plus.getAttribute('aria-haspopup')).toBe('menu');
  expect(plus.getAttribute('aria-expanded')).toBe('false');
  plus.click();
  flushSync();
  const menuItems = () => [...row.querySelectorAll<HTMLElement>('[role="menu"] [role="menuitem"]')];
  expect(menuItems().map((i) => i.dataset.node)).toEqual(['agent', 'terminal', 'browser', 'project', 'group']);
  expect(plus.getAttribute('aria-expanded')).toBe('true');
  row.querySelector<HTMLButtonElement>('[data-node="agent"]')!.click();
  flushSync();
  expect(createNewSession).toHaveBeenCalledTimes(1);
  expect(createConsoleSession).not.toHaveBeenCalled();
  expect(row.querySelector('[role="menu"]'), 'choosing a kind closes the menu').toBeNull();
  expect(plus.getAttribute('aria-expanded')).toBe('false');

  plus.click();
  flushSync();
  row.querySelector<HTMLButtonElement>('[data-node="terminal"]')!.click();
  flushSync();
  expect(createConsoleSession).toHaveBeenCalledTimes(1);
  expect(createConsoleSession).toHaveBeenCalledWith({});
  expect(createNewSession).toHaveBeenCalledTimes(1);
});

test('the "+" submenu offers browser, which creates one and records its fragment', async () => {
  win.CloudeWeb = { launchpad: {} };
  const id = '0123456789abcdef';
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST'
      ? new Response(JSON.stringify({ id, label: 'browser', url: 'about:blank', state: 'live', viewers: 0 }), { status: 201 })
      : new Response(JSON.stringify({ browsers: [] }), { status: 200 }),
  );
  vi.stubGlobal('fetch', fetchMock);
  try {
    const row = render();
    row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!.click();
    flushSync();
    const kinds = [...row.querySelectorAll<HTMLElement>('[role="menuitem"]')].map((i) => i.dataset.node);
    expect(kinds).toEqual(['agent', 'terminal', 'browser', 'project', 'group']);
    row.querySelector<HTMLButtonElement>('[data-node="browser"]')!.click();
    flushSync();
    await vi.waitFor(() => expect(location.hash).toBe(`#browser/${id}`));
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/browsers');
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
  } finally {
    history.replaceState(null, '', location.pathname);
    vi.unstubAllGlobals();
  }
});

test('the "+" submenu closes on Escape and returns focus to the button', () => {
  win.CloudeWeb = { launchpad: { createNewSession: vi.fn(async () => {}) } };
  const row = render();
  const plus = row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!;
  plus.click();
  flushSync();
  const first = row.querySelector<HTMLButtonElement>('[role="menuitem"]')!;
  expect(document.activeElement, 'the first item is focused on open').toBe(first);
  first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(row.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(plus);
});

test('the "+" submenu: arrow keys walk its items, and a pointer outside closes it', () => {
  win.CloudeWeb = { launchpad: { createNewSession: vi.fn(async () => {}), createConsoleSession: vi.fn(async () => {}) } };
  const row = render();
  row.querySelector<HTMLButtonElement>('[data-action="new-session"]')!.click();
  flushSync();
  const agent = row.querySelector<HTMLButtonElement>('[data-node="agent"]')!;
  const terminal = row.querySelector<HTMLButtonElement>('[data-node="terminal"]')!;
  expect(document.activeElement).toBe(agent);
  agent.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  expect(document.activeElement).toBe(terminal);
  terminal.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  const browser = row.querySelector<HTMLButtonElement>('[data-node="browser"]')!;
  expect(document.activeElement).toBe(browser);
  browser.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  const project = row.querySelector<HTMLButtonElement>('[data-node="project"]')!;
  expect(document.activeElement).toBe(project);
  project.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  const group = row.querySelector<HTMLButtonElement>('[data-node="group"]')!;
  expect(document.activeElement).toBe(group);
  group.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  expect(document.activeElement, 'wraps back to the first').toBe(agent);
  expect(row.querySelector('[role="menu"]')!.classList.contains('acm-menu'), 'the add component popup, not a copy').toBe(true);
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(row.querySelector('[role="menu"]')).toBeNull();
});

test('density: the control picks a mode through the real module, which persists it', () => {
  win.SessionSidebar = { panel: document.getElementById('session-sidebar-panel'), repaint: vi.fn() };
  installDensity();
  (win.SessionSidebarDensity as { init: () => void }).init();
  const row = render();
  const btn = row.querySelector<HTMLButtonElement>('[data-action="density"]')!;
  expect(btn.title).toBe('view, row detail: compact');
  btn.click();
  flushSync();
  const items = [...row.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')];
  expect(items.map((i) => i.dataset.node)).toEqual(['density-compact', 'density-cozy', 'density-detailed']);
  expect(items.map((i) => i.querySelector('.acm-label')!.textContent!.trim()), 'the mode names alone, no hint lines').toEqual(['compact', 'cozy', 'detailed']);
  expect(items[0]!.getAttribute('aria-checked')).toBe('true');
  expect(row.querySelector('[role="menu"]')!.classList.contains('acm-menu'), 'the add component popup, not a copy').toBe(true);
  items[2]!.click();
  flushSync();
  expect(localStorage.getItem('carnivore.session.sidebar.density')).toBe('detailed');
  expect(document.getElementById('session-sidebar-panel')!.getAttribute('data-density')).toBe('detailed');
  expect((win.SessionSidebar as { repaint: ReturnType<typeof vi.fn> }).repaint).toHaveBeenCalled();
  expect(row.querySelector('[role="menu"]'), 'a mode pick keeps the menu open').not.toBeNull();
  expect(btn.title).toBe('view, row detail: detailed');
});

test('density: a mode restored AFTER the controls mount is the one the control names', async () => {
  win.SessionSidebar = { panel: document.getElementById('session-sidebar-panel'), repaint: vi.fn() };
  installDensity();
  localStorage.setItem('carnivore.session.sidebar.density', 'detailed');
  const row = render();
  const btn = row.querySelector<HTMLButtonElement>('[data-action="density"]')!;
  expect(btn.dataset.density, 'nothing restored yet').toBe('compact');
  (win.SessionSidebarDensity as { init: () => void }).init();
  await Promise.resolve();
  flushSync();
  expect(btn.dataset.density).toBe('detailed');
  expect(btn.title).toBe('view, row detail: detailed');
  expect(btn.getAttribute('aria-label')).toBe('view, row detail: detailed');
});
