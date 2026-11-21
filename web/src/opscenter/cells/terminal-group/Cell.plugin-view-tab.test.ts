/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups } from '../../engine/tab-groups.svelte';
import { widgetTabId } from '../../engine/widget-tabs';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { fetchViewTicket } from '../../../lib/cplug-ui/api';
import { setPanels } from '../../../lib/cplug-ui/panel-views.svelte';
import { openWidgetMenu } from '../../../lib/item-menu/widget-gesture';
import { widgetTabItem } from './widget-tab-item';
import { tabTearOffTarget } from '../../../lib/tearoff/tearoff';
import type { CplugRow } from '../../../lib/plugins-page/cplugs-adapter';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, sessions: { data: [], status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {} } };
});
vi.mock('../../../lib/cplug-ui/api', () => ({
  fetchViewTicket: vi.fn(async () => ({ path: '/cplugs/hello/view/game/t/index.html' })),
  callViewRoute: vi.fn(),
}));

const A = 'terminal:ses_a' as SlotId;
const TAB = widgetTabId('hello.game', 'panel-ab12cd34');
const row = (installKey: string): CplugRow => ({
  id: 'hello', runtime: 'sidecar', enabled: true, state: 'active', name: 'Hello', install_key: installKey, unverified: true,
  views: [{ name: 'game', surfaces: ['panel'] }],
} as unknown as CplugRow);
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  terminalLayout.add('terminal', 'ses_a');
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  setPanels([]);
  inputFocus.forget(A);
  terminalLayout.remove(A);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
});

async function draw(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();
  await tick();
  return target;
}

const pane = (root: HTMLElement): HTMLElement => root.querySelector(`[data-tab-pane="${TAB}"]`) as HTMLElement;

test('a tab stored before the plugin list answers holds a sentence, then draws the frame when the list arrives', async () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, TAB] } });
  const root = await draw();
  expect(pane(root).querySelector('[data-panel-cell]')).toBeNull();
  setPanels([row('ab12cd34zz')]);
  flushSync();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  await tick();
  expect(pane(root).querySelector('[data-panel-cell]')).not.toBeNull();
});

test('a plugin view tab of the live install mounts the plugin view cell inside the tab pane, with its mark on screen', async () => {
  setPanels([row('ab12cd34zz')]);
  setGroups(terminalLayout, { [A]: { tabs: [A, TAB] } });
  const root = await draw();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(pane(root).querySelector('[data-widget-tab="hello.game"]')).not.toBeNull();
  expect(pane(root).querySelector('[data-panel-cell]')).not.toBeNull();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(root.querySelectorAll('[data-cplug-mark]').length).toBe(1);
  expect(root.querySelector('[data-cplug-mark]')?.hasAttribute('data-unverified')).toBe(true);
});

test('a tab bound to another install shows the off note and no frame', async () => {
  setPanels([row('ffffffffzz')]);
  setGroups(terminalLayout, { [A]: { tabs: [A, TAB] } });
  const root = await draw();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(pane(root).querySelector('[data-panel-cell]')).not.toBeNull();
  expect(pane(root).querySelector('iframe')).toBeNull();
  expect(pane(root).querySelector('[data-cplug-mark]')).toBeNull();
});

test('a plugin view tab has no tear-off page', () => {
  expect(tabTearOffTarget(TAB)).toBeNull();
  expect(tabTearOffTarget(widgetTabId('core.tasks'))).toEqual({ kind: 'widget', id: 'core.tasks' });
});

test('a ui.menu request from the frame opens the TAB\'s widget menu, never the terminal component\'s frame menu', async () => {
  setPanels([row('ab12cd34zz')]);
  setGroups(terminalLayout, { [A]: { tabs: [A, TAB] } });
  const root = await draw();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  await tick();
  const shield = pane(root).querySelector('[data-cplug-gate]') as HTMLElement;
  openWidgetMenu(null, shield);
  flushSync();
  const nodes = [...document.querySelectorAll('[role="menuitem"]')].map((el) => (el as HTMLElement).dataset.node);
  expect(nodes).toEqual(['close-tab']);
});

test('a plugin view tab whose plugin is gone reads plugin off with the plug glyph, and its pane says why', async () => {
  const gone = widgetTabId('gone.view', 'panel-ab12cd34');
  expect(widgetTabItem(gone, 'gone.view')).toMatchObject({ name: 'plugin off', glyph: 'plug' });
  expect(widgetTabItem(widgetTabId('core.nothing'), 'core.nothing').name).toBe('missing widget');
  setGroups(terminalLayout, { [A]: { tabs: [A, gone] } });
  const root = await draw();
  expect(root.querySelector(`[data-tab-pane="${gone}"]`)?.textContent).toContain('this plugin is off or removed');
});

test('a plugin view tab that was never shown fetches no ticket; selecting it fetches one (lazy first mount)', async () => {
  const fetchTicket = vi.mocked(fetchViewTicket);
  fetchTicket.mockClear();
  setPanels([row('ab12cd34zz')]);
  setGroups(terminalLayout, { [A]: { tabs: [A, TAB] } });
  const root = await draw();
  expect(pane(root).querySelector('[data-panel-cell]')).toBeNull();
  expect(fetchTicket).not.toHaveBeenCalled();
  (root.querySelector(`[data-tab="${TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  await tick();
  expect(fetchTicket).toHaveBeenCalledTimes(1);
});
