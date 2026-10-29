/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();
import type { LedgerSnapshot } from '../api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as 'loading' | 'ok',
  data: null as LedgerSnapshot | null,
  fetchedAt: null as number | null,
  error: null as string | null,
}));
vi.mock('../api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, ledger: fakeLedger, primarySessionId: () => '' };
});
vi.mock('../../lib/item-settings/store.svelte', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, isWidgetDisabled: () => false };
});
const listing = vi.hoisted(() => ({
  data: [{ session: { id: 'ses_a', working_dir: '/work/a' }, session_row_id: 5, label: 'alpha', agent_family: 'shell' }] as unknown[],
}));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));
vi.mock('../cells/registry', async (importOriginal) => {
  const real = await importOriginal<typeof import('../cells/registry')>();
  return { ...real, entryFor: (slot: string) => (slot.includes(':') ? undefined : real.entryFor(slot as never)) };
});
vi.mock('../../lib/browser/api.svelte', () => ({ browsers: { data: [] } }));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import WidgetDrawer from './WidgetDrawer.svelte';
import DrawerZone from '../../lib/drawer-zone/DrawerZone.svelte';
import { homeLayout, terminalLayout } from '../engine/layout.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import { editorSeams, enterLayoutEditor, finishLayoutEditor } from './editor.svelte';
import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
import { sidebarTabs } from '../../lib/dynamic-tabs/tab-store.svelte';
import { widgetArea } from '../../lib/dynamic-tabs/widget-area.svelte';
import { dismissRefusal, placementRefusal } from '../widgets/chrome/refusal-toast.svelte';

const BOX = {
  drawer: { left: 0, right: 200, top: 0, bottom: 380 },
  screen: { left: 300, right: 1300, top: 0, bottom: 900 },
  row: { left: 300, right: 1300, top: 0, bottom: 200 },
  zone: { left: 0, right: 200, top: 400, bottom: 700 },
  item: { left: 0, right: 200, top: 400, bottom: 500 },
  glance: { left: 0, right: 200, top: 600, bottom: 700 },
  none: { left: 0, right: 0, top: 0, bottom: 0 },
};

function boxOf(el: Element): DOMRect {
  const b = el.closest('.le-drawer') && el.classList.contains('le-drawer')
    ? BOX.drawer
    : el.classList.contains('oc-surface')
      ? BOX.screen
      : el.classList.contains('oc-row')
        ? BOX.row
        : el.id === 'session-sidebar-ledger'
      ? BOX.zone
      : el.hasAttribute('data-glance-area')
        ? BOX.glance
        : el.hasAttribute('data-zone-item')
          ? BOX.item
          : BOX.none;
  return { ...b, x: b.left, y: b.top, width: b.right - b.left, height: b.bottom - b.top, toJSON: () => b } as DOMRect;
}

const realRect = Element.prototype.getBoundingClientRect;
let drawerApp: ReturnType<typeof mount> | null = null;
let zoneApp: ReturnType<typeof mount> | null = null;
let zoneHost: HTMLElement;
const real = { ...editorSeams };

const row = (widget: string): HTMLElement => document.querySelector<HTMLElement>(`[data-le-card][data-widget="${widget}"]`)!;
const pointer = (el: HTMLElement, type: string, x: number, y: number): void => {
  el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }));
  flushSync();
};
const zoneDrop = (): string | null => zoneHost.querySelector<HTMLElement>('[data-drawer-zone]')!.getAttribute('data-drop');
const glanceDrop = (): string | null => zoneHost.querySelector<HTMLElement>('[data-glance-area]')!.getAttribute('data-drop');

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  Element.prototype.getBoundingClientRect = function (this: Element) {
    return boxOf(this);
  };
  fakeLedger.data = { accounts: [], total: { accounts: 0, windows: [] }, loop: { alive: true, last_pass_at: null } } as never;
  drawerZone.stored = null;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => null,
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  homeLayout.resetAll();
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  enterLayoutEditor();
  widgetArea.set(sidebarTabs.active(), 'full');
  drawerApp = mount(WidgetDrawer, { target: document.body, props: { store: homeLayout, page: 'home' } });
  zoneHost = document.createElement('div');
  zoneHost.id = 'session-sidebar-ledger';
  document.body.appendChild(zoneHost);
  zoneApp = mount(DrawerZone, { target: zoneHost });
  flushSync();
});

afterEach(() => {
  if (drawerApp) unmount(drawerApp);
  if (zoneApp) unmount(zoneApp);
  drawerApp = zoneApp = null;
  finishLayoutEditor();
  dismissRefusal();
  Element.prototype.getBoundingClientRect = realRect;
  Object.assign(editorSeams, real);
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
  document.body.replaceChildren();
});

describe('a drawer row carried onto the sidebar', () => {
  test('lands in the widget area at its insertion mark, the area marked as a drop target meanwhile', () => {
    expect(zoneDrop()).toBeNull();
    const card = row('core.keep-awake');
    pointer(card, 'pointerdown', 50, 100);
    pointer(card, 'pointermove', 50, 200);
    expect(zoneDrop()).toBe('open');
    expect(glanceDrop()).toBe('open');
    pointer(card, 'pointermove', 50, 480);
    expect(zoneDrop()).toBe('aimed');
    expect(zoneHost.querySelector('[data-zone-mark]')).not.toBeNull();
    expect(document.querySelector('.le-ghost--aimed')).not.toBeNull();
    pointer(card, 'pointerup', 50, 480);
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger', 'core.keep-awake']);
    expect(zoneDrop()).toBeNull();
  });

  test('lands in the glance area', () => {
    const card = row('core.questions');
    pointer(card, 'pointerdown', 50, 100);
    pointer(card, 'pointermove', 50, 650);
    expect(glanceDrop()).toBe('aimed');
    expect(zoneDrop()).toBe('open');
    expect(zoneHost.querySelector('[data-glance-mark]')).not.toBeNull();
    pointer(card, 'pointerup', 50, 650);
    expect(drawerZone.glance.map((placement) => placement.widget)).toContain('core.questions');
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger']);
  });

  test('a widget that once did not declare the drawer lands in both areas, never drawn refused', () => {
    const card = row('core.notes');
    pointer(card, 'pointerdown', 50, 100);
    pointer(card, 'pointermove', 50, 480);
    expect(zoneDrop()).toBe('aimed');
    expect(zoneHost.querySelector('[data-zone-mark]')).not.toBeNull();
    expect(document.querySelector('.le-ghost--refused')).toBeNull();
    pointer(card, 'pointerup', 50, 480);
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger', 'core.notes']);
    expect(placementRefusal.line).toBe('');
    const again = row('core.notes');
    pointer(again, 'pointerdown', 50, 100);
    pointer(again, 'pointermove', 50, 650);
    expect(glanceDrop()).toBe('aimed');
    pointer(again, 'pointerup', 50, 650);
    expect(drawerZone.glance.map((placement) => placement.widget)).toContain('core.notes');
  });

  test('a widget the area already holds asks first (Joe, 2026-10-04): move here moves it to the mark, cancel leaves it', () => {
    drawerZone.add('core.keep-awake');
    flushSync();
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger', 'core.keep-awake']);
    const card = row('core.keep-awake');
    expect(card.getAttribute('aria-disabled'), 'a placed widget is never disabled').not.toBe('true');
    const carry = (): void => {
      pointer(card, 'pointerdown', 50, 100);
      pointer(card, 'pointermove', 50, 420);
      expect(zoneDrop()).toBe('aimed');
      pointer(card, 'pointerup', 50, 420);
      flushSync();
    };
    carry();
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger', 'core.keep-awake']);
    const prompt = document.querySelector<HTMLElement>('[data-duplicate-prompt]')!;
    expect(prompt.dataset['duplicatePrompt']).toBe('one');
    expect(prompt.textContent).toContain('already here');
    expect(prompt.querySelector('[data-dupe-copy]'), 'a one-copy widget offers no second copy').toBeNull();
    prompt.querySelector<HTMLElement>('[data-dupe-cancel]')!.click();
    flushSync();
    expect(document.querySelector('[data-duplicate-prompt]')).toBeNull();
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger', 'core.keep-awake']);
    carry();
    document.querySelector<HTMLElement>('[data-duplicate-prompt] [data-dupe-move]')!.click();
    flushSync();
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.keep-awake', 'core.ledger']);
    expect(placementRefusal.line).toBe('');
  });

  test('a row lands on the dashboard grid too', async () => {
    const screen = document.createElement('div');
    screen.id = 'launchpad-screen';
    const surface = document.createElement('div');
    surface.className = 'oc-surface';
    const first = document.createElement('div');
    first.className = 'oc-row';
    first.dataset['row'] = homeLayout.state.layout.rows[0]!.id;
    surface.appendChild(first);
    screen.appendChild(surface);
    document.body.appendChild(screen);
    const onScreen = (): string[] => homeLayout.state.layout.rows.flatMap((r) => r.slots.map((slot) => slot.id));
    expect(onScreen()).not.toContain('notes');
    const card = row('core.notes');
    pointer(card, 'pointerdown', 50, 100);
    pointer(card, 'pointermove', 800, 100);
    expect(document.querySelector('.le-ghost--aimed')).not.toBeNull();
    pointer(card, 'pointerup', 800, 100);
    await Promise.resolve();
    flushSync();
    expect(onScreen()).toContain('notes');
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.ledger']);
  });

  test('a press still adds to the screen', () => {
    const card = row('core.keep-awake');
    card.click();
    flushSync();
    expect(homeLayout.state.layout.rows.flatMap((r) => r.slots.map((slot) => slot.id))).toContain('keep-awake');
  });
});

describe('a family carried onto the sidebar (Joe (ccsliinc), 2026-10-03: "yes drop anywhere")', () => {
  test('the analytics row lands in the widget area as a fresh chart each time, never refused', () => {
    for (const _ of [1, 2]) {
      const card = row('core.analytics');
      pointer(card, 'pointerdown', 50, 100);
      pointer(card, 'pointermove', 50, 480);
      expect(zoneDrop()).toBe('aimed');
      pointer(card, 'pointerup', 50, 480);
    }
    expect(placementRefusal.line).toBe('');
    const copies = drawerZone.items.filter((item) => item.widget === 'core.analytics');
    expect(copies).toHaveLength(2);
    expect(new Set(copies.map((item) => item.target)).size).toBe(2);
    for (const copy of copies) expect(analytics.charts[copy.target!]).toBeDefined();
    expect(zoneHost.querySelectorAll('[data-zone-item^="core.analytics@"]')).toHaveLength(2);
  });

  test('the analytics row lands in the glance area with its chart as the placement target', () => {
    const card = row('core.analytics');
    pointer(card, 'pointerdown', 50, 100);
    pointer(card, 'pointermove', 50, 650);
    expect(glanceDrop()).toBe('aimed');
    pointer(card, 'pointerup', 50, 650);
    const placed = drawerZone.glance.find((placement) => placement.widget === 'core.analytics');
    expect(placed?.options['target']).toBeTypeOf('string');
    expect(analytics.charts[String(placed!.options['target'])]).toBeDefined();
  });

  test('a window row carried onto the widget area folds it open, and the pick lands there as a copy', () => {
    unmount(drawerApp!);
    terminalLayout.resetAll();
    editorSeams.page = () => 'terminal';
    editorSeams.store = (p) => (p === 'terminal' ? terminalLayout : null);
    drawerApp = mount(WidgetDrawer, { target: document.body, props: { store: terminalLayout, page: 'terminal' } });
    flushSync();
    const segment = document.querySelector<HTMLElement>('[data-window-picker] [data-picker-entry="terminal"]')!;
    pointer(segment, 'pointerdown', 50, 100);
    pointer(segment, 'pointermove', 50, 480);
    expect(zoneDrop()).toBe('aimed');
    pointer(segment, 'pointerup', 50, 480);
    document.querySelector<HTMLButtonElement>('[data-picker-row="ses_a"]')!.click();
    flushSync();
    expect(drawerZone.items.map((item) => [item.widget, item.target ?? null])).toEqual([
      ['core.ledger', null],
      ['core.terminal', 'row:5'],
    ]);
    expect(terminalLayout.state.layout.rows.flatMap((r) => r.slots.map((slot) => slot.id))).not.toContain('terminal:row:5');
    expect(zoneHost.querySelector('[data-zone-cell="core.terminal"][data-zone-target="row:5"]')).not.toBeNull();
  });
});
