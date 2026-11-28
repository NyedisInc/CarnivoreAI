/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, selectTab, setGroups } from '../../engine/tab-groups.svelte';
import { setParking, TRANSIT_MS } from '../terminal-live/parking';
import { widgetTabId } from '../../engine/widget-tabs';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const counts = { started: 0, disposed: 0 };

vi.mock('../terminal-live/client', () => ({
  startLiveTerminal: () => {
    counts.started += 1;
    return { client: { fake: true }, dispose(): void { counts.disposed += 1; } };
  },
}));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../registry', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../registry')>();
  const Stub = (await import('./fixtures/StubWidgetCell.svelte')).default;
  return { ...actual, entryFor: (slot: string) => (slot.startsWith('widget') ? { ...(actual.entryFor(slot as never) ?? {}), component: Stub } : actual.entryFor(slot as never)) };
});
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string) => ({
    session: { id }, label: id, agent_family: 'shell', tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_a'), row('ses_b'), row('ses_c')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c';
const NOTES = widgetTabId('core.notes');
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  counts.started = 0;
  counts.disposed = 0;
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  app = mount(TabbedFrame, { target: document.body.appendChild(document.createElement('div')), props: { slot: A } });
  flushSync();
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

test('adding a background terminal tab defers start until visited, then starts exactly one and disposes none (#3290)', () => {
  expect(counts.started).toBe(1);
  setGroups(terminalLayout, { [A]: { tabs: [A, B, C] } });
  flushSync();
  expect(counts.started).toBe(1);
  expect(counts.disposed).toBe(0);
  selectTab(terminalLayout, A, C);
  flushSync();
  expect(counts.started).toBe(2);
  expect(counts.disposed).toBe(0);
});

test('adding a widget tab starts and disposes no terminal', () => {
  const before = counts.started;
  setGroups(terminalLayout, { [A]: { tabs: [A, B, NOTES] } });
  flushSync();
  expect(counts.started).toBe(before);
  expect(counts.disposed).toBe(0);
});

test('closing a visited tab disposes only that tab, reordering and switching touch no live terminal', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, B, C] } });
  flushSync();
  selectTab(terminalLayout, A, B);
  flushSync();
  selectTab(terminalLayout, A, C);
  flushSync();
  const started = counts.started;
  expect(started).toBe(3);
  setGroups(terminalLayout, { [A]: { tabs: [A, C, B] } }); // reorder
  flushSync();
  selectTab(terminalLayout, A, B);
  flushSync();
  expect(counts.started - started).toBe(0);
  expect(counts.disposed).toBe(0);
  setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
  flushSync();
  expect(counts.started - started).toBe(0);
  expect(counts.disposed).toBe(1);
});

test('a visited tab taken down and drawn again at once (a move) keeps its live terminal; a closed one ends after the hold', () => {
  vi.useFakeTimers();
  setParking(true);
  try {
    selectTab(terminalLayout, A, B);
    flushSync();
    selectTab(terminalLayout, A, A);
    flushSync();
    const before = { started: counts.started, disposed: counts.disposed };
    setGroups(terminalLayout, { [A]: { tabs: [A] } });
    flushSync();
    setGroups(terminalLayout, { [A]: { tabs: [A, B] } });
    flushSync();
    expect(counts.started - before.started).toBe(0);
    expect(counts.disposed - before.disposed).toBe(0);
    setGroups(terminalLayout, { [A]: { tabs: [A] } });
    flushSync();
    expect(counts.disposed - before.disposed).toBe(0);
    vi.advanceTimersByTime(TRANSIT_MS + 1);
    expect(counts.disposed - before.disposed).toBe(1);
  } finally {
    setParking(false);
    vi.useRealTimers();
  }
});
