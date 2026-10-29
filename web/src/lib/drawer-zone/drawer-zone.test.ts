/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({ status: 'ok' as const, data: null as LedgerSnapshot | null, fetchedAt: null as number | null, error: null as string | null }));
vi.mock('../../opscenter/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), ledger: fakeLedger, primarySessionId: () => '' }));
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/cells/registry')>();
  const { default: ZoneProbeCell } = await import('../../opscenter/shell/fixtures/ZoneProbeCell.svelte');
  return { ...real, entryFor: (slot: string) => (slot === 'keep-awake' ? { component: ZoneProbeCell } : real.entryFor(slot as never)) };
});

import DrawerZone from './DrawerZone.svelte';
import { drawerZone } from './zone-store.svelte';
import { createGlanceZone, glanceEntries, GLANCE_ZONE_KEY } from './area-zones';
import { drawerLayout } from '../drawer-layout/drawer-layout.svelte';
import { widgetArea } from '../dynamic-tabs/widget-area.svelte';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

class FakeObserver {
  static last: FakeObserver | null = null;
  targets = new Set<Element>();
  constructor(private callback: IntersectionObserverCallback) {
    FakeObserver.last = this;
  }
  observe(el: Element): void { this.targets.add(el); }
  unobserve(el: Element): void { this.targets.delete(el); }
  disconnect(): void { this.targets.clear(); }
  report(el: Element, isIntersecting: boolean): void {
    this.callback([{ target: el, isIntersecting } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}

const KEEP = 'core.keep-awake';
const KEEP_BODY = 'drawer-zone:core.keep-awake';

let app: ReturnType<typeof mount> | null = null;
let host: HTMLElement;
const tab = (): string => sidebarTabs.active();
const setArea = (state: 'full' | 'glance' | 'closed'): void => {
  widgetArea.set(tab(), state);
  flushSync();
};
const card = (key: string): HTMLElement | null => host.querySelector<HTMLElement>(`[data-zone-item="${key}"]`);
const probe = (): HTMLElement | null => host.querySelector<HTMLElement>(`[data-stub="${KEEP_BODY}"]`);
const readings = (): Record<string, string> =>
  Object.fromEntries(drawerLayout().cards.map((zone) => [zone.spec.key, zone.visibility(zone.tabs[0]!.key)]));

beforeEach(() => {
  vi.stubGlobal('VisibilityObserver', FakeObserver);
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  vi.stubGlobal('PreferenceBridge', { read: () => null, write: async () => ({ status: 'committed' }), follow: () => () => {} });
  drawerZone.stored = null;
  layoutEditor.active = false;
  host = document.createElement('div');
  host.id = 'session-sidebar-ledger';
  document.body.append(host);
  app = mount(DrawerZone, { target: host });
  flushSync();
  drawerZone.add(KEEP);
  setArea('full');
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  setArea('full');
  vi.unstubAllGlobals();
});

describe('the drawer area cards are one-tab zones', () => {
  test('a closed area reads parked for every card and draws none; at glance too; full again reads shown', () => {
    expect(readings()).toEqual({ 'drawer:core.ledger': 'shown', [`drawer:${KEEP}`]: 'shown' });
    expect(card(KEEP)!.dataset['zoneVisible']).toBe('shown');
    expect(probe()!.dataset['widgetVisible']).toBe('shown');

    setArea('closed');
    expect(readings(), 'every card of a closed area is parked').toEqual({ 'drawer:core.ledger': 'parked', [`drawer:${KEEP}`]: 'parked' });
    expect(host.querySelector('[data-zone-item]'), 'a parked card draws no body, so it asks for nothing').toBeNull();

    setArea('glance');
    expect(Object.values(readings())).toEqual(['parked', 'parked']);
    expect(host.querySelector('[data-zone-item]')).toBeNull();

    setArea('full');
    expect(Object.values(readings())).toEqual(['shown', 'shown']);
    expect(probe()!.dataset['widgetVisible']).toBe('shown');
  });

  test('the card header is the zone tab header under the body key, where the cell declares its actions; no pane box, no tab pane', () => {
    const zone = drawerLayout().cards.find((one) => one.spec.key === `drawer:${KEEP}`)!;
    expect(zone.spec.menuHost).toBe('drawer-card');
    expect(zone.toolbar?.hostId).toBe(KEEP_BODY);
    expect(probe()!.dataset['host']).toBe(KEEP_BODY);
    expect(declaredActionsFor(KEEP_BODY).map((one) => one.id)).toContain(`act-${KEEP_BODY}`);
    expect(probe()!.hasAttribute('data-pane-visible'), 'a one-tab zone is not a tab group').toBe(false);
    expect(host.querySelector('.zone-pane'), 'no element between the card and its body').toBeNull();
  });

  test('a card off screen, or under a hidden document, reads hidden and its widget with it', () => {
    const el = card(KEEP)!;
    expect(FakeObserver.last?.targets.has(el), 'the card itself is the observed box').toBe(true);
    FakeObserver.last!.report(el, false);
    flushSync();
    expect(el.dataset['zoneVisible']).toBe('hidden');
    expect(probe()!.dataset['widgetVisible']).toBe('hidden');
    FakeObserver.last!.report(el, true);
    flushSync();
    expect(el.dataset['zoneVisible']).toBe('shown');

    const flip = (state: 'hidden' | 'visible'): void => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
      document.dispatchEvent(new Event('visibilitychange'));
      flushSync();
    };
    flip('hidden');
    expect(el.dataset['zoneVisible']).toBe('hidden');
    expect(probe()!.dataset['widgetVisible']).toBe('hidden');
    flip('visible');
    expect(el.dataset['zoneVisible']).toBe('shown');
  });

  test('a removed item leaves the layout with its zone', () => {
    drawerZone.remove(KEEP);
    flushSync();
    expect(drawerLayout().cards.map((zone) => zone.spec.key)).toEqual(['drawer:core.ledger']);
  });
});

describe('the glance row is one zone', () => {
  test('its tabs are the glance placements, all parked, and a tile menu opens through it', () => {
    const id = drawerZone.addGlance(KEEP, true)!;
    const opened: string[] = [];
    const zone = createGlanceZone(glanceEntries, (entry) => opened.push(entry.key));
    expect(zone.spec.key).toBe(GLANCE_ZONE_KEY);
    expect(zone.spec.menuHost).toBe('glance');
    expect(zone.tabs.map((one) => one.key)).toContain(id);
    expect(zone.tabs.map((one) => zone.visibility(one.key)).every((one) => one === 'parked'), 'a tile is a key, never a body').toBe(true);
    expect(zone.openMenu(id, document.body)).toBe(true);
    expect(zone.openMenu('g-none', document.body), 'no placement, no menu').toBe(false);
    expect(opened).toEqual([id]);
    drawerZone.removeGlance(id);
  });
});
