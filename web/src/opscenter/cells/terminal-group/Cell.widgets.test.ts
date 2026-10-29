/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups, tabsFor } from '../../engine/tab-groups.svelte';
import { widgetTabId } from '../../engine/widget-tabs';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../registry', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../registry')>();
  const Stub = (await import('./fixtures/StubWidgetCell.svelte')).default;
  return { ...actual, entryFor: (slot: string) => ({ ...(actual.entryFor(slot as never) ?? {}), component: Stub }) };
});
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, sessions: { data: [], status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {} } };
});

const A = 'terminal:ses_a' as SlotId;
const NOTES = widgetTabId('core.notes');
const MISSING = widgetTabId('core.nothing');
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  terminalLayout.add('terminal', 'ses_a');
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  terminalLayout.remove(A);
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

function item(id: string): HTMLButtonElement {
  return document.querySelector(`[role="menuitem"][data-node="${id}"]`) as HTMLButtonElement;
}

test('the plus menu lists widgets by category and picking one opens it as a tab here', () => {
  const root = draw();
  (root.querySelector('.oc-tab-new') as HTMLButtonElement).click();
  flushSync();
  item('widget').click();
  flushSync();
  const category = document.querySelector('[role="menuitem"][data-node="widget/tools"]') as HTMLButtonElement;
  expect(category).toBeTruthy();
  category.click();
  flushSync();
  item('widget/core.notes').click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A, NOTES]);
  expect(root.querySelector(`[data-tab="${NOTES}"]`)?.getAttribute('aria-selected')).toBe('true');
});

test('a widget tab draws the widget through the shell and reads its title with no status light', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, NOTES] } });
  const root = draw();
  const pane = root.querySelector(`[data-tab-pane="${NOTES}"]`) as HTMLElement;
  expect(pane.querySelector('[data-widget-tab="core.notes"]')).not.toBeNull();
  expect(pane.querySelector('[data-stub-widget]')).not.toBeNull();
  const tab = root.querySelector(`[data-tab="${NOTES}"]`) as HTMLElement;
  expect(tab.textContent?.trim().length).toBeGreaterThan(0);
  expect(tab.querySelector('.status-led, [data-status-led]')).toBeNull();
});

test('a widget tab is hidden while another tab shows, shown while it does, and the active tab is not written to the synced group', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, NOTES] } });
  const root = draw();
  const visible = (key: string): string | null => root.querySelector(`[data-zone-pane="${key}"]`)?.getAttribute('data-zone-visible') ?? null;
  (root.querySelector(`[data-tab="${A}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(visible(NOTES)).toBe('hidden');
  (root.querySelector(`[data-tab="${NOTES}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(visible(NOTES)).toBe('shown');
  expect(tabsFor(terminalLayout, A)).toEqual([A, NOTES]);
});

test('a widget this build does not carry is one sentence and a plain tab name, and its x removes it', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, MISSING] } });
  const root = draw();
  const pane = root.querySelector(`[data-tab-pane="${MISSING}"]`) as HTMLElement;
  expect(pane.textContent).toContain('this widget is not available here');
  expect(pane.querySelector('[data-stub-widget]')).toBeNull();
  expect((root.querySelector(`[data-tab="${MISSING}"]`) as HTMLElement).textContent).toContain('missing widget');
  (root.querySelector(`[data-tab-close="${MISSING}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A]);
});

test('a right-click on a widget tab, active or not, opens the widget menu with close tab', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, NOTES] } });
  const root = draw();
  (root.querySelector(`[data-tab="${A}"]`) as HTMLButtonElement).click();
  flushSync();
  const tab = root.querySelector(`[data-tab="${NOTES}"]`) as HTMLElement;
  tab.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
  flushSync();
  expect(item('close-tab')).not.toBeNull();
  item('close-tab').click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A]);
});
