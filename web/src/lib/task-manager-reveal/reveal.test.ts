/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const h = vi.hoisted(() => ({
  focus: vi.fn(async (): Promise<string | null> => null),
  rail: { side: [] as unknown[], bottom: [] as unknown[] },
  drawer: [] as unknown[],
  shown: { side: [] as string[], bottom: [] as string[] },
  barShow: { side: true, bottom: true },
  press: vi.fn(),
  setBar: vi.fn(),
  lead: vi.fn(),
  showDrawer: vi.fn(),
}));

vi.mock('./task-manager-open', () => ({ focusTaskManagerItem: h.focus }));
vi.mock('../session-rail/rail-store.svelte', () => ({
  railStores: { side: { get items() { return h.rail.side; } }, bottom: { get items() { return h.rail.bottom; } } },
}));
vi.mock('../session-rail/slideout.svelte', () => ({
  railSlideout: {
    shown: (edge: 'side' | 'bottom') => h.shown[edge],
    press: (edge: 'side' | 'bottom', key: string) => { h.press(edge, key); h.shown[edge] = [key]; return true; },
  },
}));
vi.mock('../widget-bars/bar-settings.svelte', () => ({
  widgetBars: {
    get view() { return { side: { show: h.barShow.side }, bottom: { show: h.barShow.bottom } }; },
    set: async (edge: 'side' | 'bottom', patch: { show: boolean }) => { h.setBar(edge, patch); h.barShow[edge] = patch.show; },
  },
}));
vi.mock('../widget-bars/bar-lead.svelte', () => ({ barLead: { take: h.lead } }));
vi.mock('../drawer-zone/zone-store.svelte', () => ({ drawerZone: { get items() { return h.drawer; } } }));
vi.mock('../drawer/show-drawer', () => ({ showDrawerForPage: h.showDrawer }));

import { revealWish } from '../../cplugs/sdk/task-manager-reveal.svelte';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { t } from '../i18n/index.svelte';
import { mountedWidget, openTaskManagerItem, revealInTaskManager, showTaskManager } from './reveal';

const ALL = { widget: 'core.task-manager', view: 'all', look: null };

function mountWidget(attrs: Record<string, string>, inside: HTMLElement = document.body): HTMLElement {
  const el = document.createElement('div');
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  inside.appendChild(el);
  return el;
}

beforeEach(() => {
  h.focus.mockClear();
  h.press.mockClear();
  h.setBar.mockClear();
  h.lead.mockClear();
  h.showDrawer.mockClear();
  h.rail.side = [];
  h.rail.bottom = [];
  h.drawer = [];
  h.shown.side = [];
  h.shown.bottom = [];
  h.barShow.side = true;
  h.barShow.bottom = true;
  revealWish.id = null;
});
afterEach(() => {
  document.body.innerHTML = '';
});

describe('a Task Manager widget is already on screen', () => {
  test('it is focused and scrolled into view, the focus route is written, and nothing else opens', async () => {
    const widget = mountWidget({ 'data-task-manager-all-cell': '' });
    const scroll = vi.fn();
    widget.scrollIntoView = scroll;
    const result = await revealInTaskManager('12', 345);
    expect(result).toEqual({ outcome: 'shown', reason: null });
    expect(h.focus).toHaveBeenCalledWith('12', 345);
    expect(scroll).toHaveBeenCalled();
    expect(document.activeElement).toBe(widget);
    expect(h.press).not.toHaveBeenCalled();
    expect(h.showDrawer).not.toHaveBeenCalled();
    expect(sidebarTabs.active()).not.toBe('huddle');
    expect(revealWish.id).toBe(345);
  });

  test('a widget pinned to a DIFFERENT project does not count, one pinned to the item\'s project does', () => {
    mountWidget({ 'data-task-manager-cell': '7' });
    expect(mountedWidget('12')).toBeNull();
    const own = mountWidget({ 'data-task-manager-cell': '12' });
    expect(mountedWidget('12')).toBe(own);
  });

  test('a widget under an inert or hidden ancestor (a retracted bar) is not "on screen"', () => {
    const shut = mountWidget({ inert: '' });
    mountWidget({ 'data-task-manager-all-cell': '' }, shut);
    expect(mountedWidget('12')).toBeNull();
  });
});

describe('the widget is in a bar that is shut or hidden', () => {
  test('a shut slide-out is put out on its bar, which leads; the bar is already shown so it is not rewritten', async () => {
    h.rail.side = [{ widget: 'core.files', look: null }, ALL];
    const result = await revealInTaskManager('12', 345);
    expect(result.outcome).toBe('raised');
    expect(h.press).toHaveBeenCalledWith('side', 'core.task-manager');
    expect(h.setBar).not.toHaveBeenCalled();
    expect(h.lead).toHaveBeenCalledWith('side');
    expect(h.focus).toHaveBeenCalledWith('12', 345);
    expect(h.press.mock.invocationCallOrder[0]!).toBeLessThan(h.focus.mock.invocationCallOrder[0]!);
    expect(sidebarTabs.active()).not.toBe('huddle');
  });

  test('a hidden bar is shown first (a stored setting), then its slide-out opens', async () => {
    h.rail.bottom = [ALL];
    h.barShow.bottom = false;
    const result = await revealInTaskManager('12', 345);
    expect(result.outcome).toBe('raised');
    expect(h.setBar).toHaveBeenCalledWith('bottom', { show: true });
    expect(h.press).toHaveBeenCalledWith('bottom', 'core.task-manager');
  });

  test('a slide-out that is already out is left alone', async () => {
    h.rail.side = [ALL];
    h.shown.side = ['core.task-manager'];
    await revealInTaskManager('12', 345);
    expect(h.press).not.toHaveBeenCalled();
    expect(h.focus).toHaveBeenCalled();
  });

  test('the drawer\'s widget area while the drawer is shut: the drawer opens for this page', async () => {
    h.drawer = [ALL];
    const result = await revealInTaskManager('12', 345);
    expect(result.outcome).toBe('raised');
    expect(h.showDrawer).toHaveBeenCalled();
  });
});

describe('no Task Manager widget is placed anywhere', () => {
  test('the answer is missing, the focus route is not written and no drawer tab is selected', async () => {
    h.rail.side = [{ widget: 'core.files', look: null }];
    const result = await revealInTaskManager('12', 345);
    expect(result).toEqual({ outcome: 'missing', reason: null });
    expect(h.focus).not.toHaveBeenCalled();
    expect(h.press).not.toHaveBeenCalled();
    expect(revealWish.id).toBeNull();
    expect(sidebarTabs.active()).not.toBe('huddle');
  });
});

describe('the focus route refuses', () => {
  test('its reason comes back and the wish is dropped', async () => {
    mountWidget({ 'data-task-manager-all-cell': '' });
    h.focus.mockResolvedValueOnce('the huddle plugin is off.');
    const result = await revealInTaskManager('12', 345);
    expect(result).toEqual({ outcome: 'refused', reason: 'the huddle plugin is off.' });
    expect(revealWish.id).toBeNull();
  });
});

describe('openTaskManagerItem, the one open for the waiting on you widget, the bell and the Automations page (#1800)', () => {
  test('a Task Manager widget on screen shows the item: no sentence and the Swarm tab is never selected', async () => {
    mountWidget({ 'data-task-manager-all-cell': '' });
    const before = sidebarTabs.active();
    expect(await openTaskManagerItem('12', 345)).toBeNull();
    expect(h.focus).toHaveBeenCalledWith('12', 345);
    expect(sidebarTabs.active()).toBe(before);
    expect(sidebarTabs.active()).not.toBe('huddle');
  });

  test('no Task Manager widget placed says so, writes nothing and still does not land in the Swarm tab', async () => {
    expect(await openTaskManagerItem('12', 345)).toBe(t('opscenter.cell.task_list.no_tm'));
    expect(h.focus).not.toHaveBeenCalled();
    expect(sidebarTabs.active()).not.toBe('huddle');
  });

  test('the focus route refusing comes back as its own words', async () => {
    mountWidget({ 'data-task-manager-all-cell': '' });
    h.focus.mockResolvedValueOnce('the huddle plugin is off.');
    expect(await openTaskManagerItem('12', 345)).toBe('the huddle plugin is off.');
  });
});

describe('showTaskManager brings the widget up without writing any item focus (docs/ui-show.md)', () => {
  test('a widget on screen is focused; a shut bar is put out; nowhere answers missing; the focus route is never written', async () => {
    expect(await showTaskManager()).toBe('missing');
    h.rail.side = [ALL];
    expect(await showTaskManager()).toBe('raised');
    expect(h.press).toHaveBeenCalledWith('side', 'core.task-manager');
    const widget = mountWidget({ 'data-task-manager-all-cell': '' });
    widget.scrollIntoView = vi.fn();
    expect(await showTaskManager()).toBe('shown');
    expect(document.activeElement).toBe(widget);
    expect(h.focus).not.toHaveBeenCalled();
  });
});
