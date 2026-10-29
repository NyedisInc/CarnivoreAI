/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount, type Component } from 'svelte';
import CellHost from '../CellHost.svelte';
import CellInFrame from './fixtures/CellInFrame.svelte';
import ZoneProbeCell from './fixtures/ZoneProbeCell.svelte';
import { homeLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import type { CellProps } from '../lib/cell';
import { declaredActionsFor } from '../widgets/menu/declared-actions.svelte';
import { createGridZone, gridHeaderId, gridTabKey } from './grid-zone';
import { setLocale } from '../../lib/i18n/index.svelte';

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

let app: ReturnType<typeof mount> | null = null;
const frame = (slot: string): HTMLElement => document.querySelector<HTMLElement>(`.oc-frame[data-cell="${slot}"]`)!;

beforeEach(() => {
  vi.stubGlobal('VisibilityObserver', FakeObserver);
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('a grid slot is a one-tab zone', () => {
  test('a widget slot declares its actions on grid:<slot>#<tab>, and its tab reads hidden while the board is off screen', () => {
    app = mount(CellHost, { target: document.body, props: { id: 'notes' as SlotId, store: homeLayout } });
    flushSync();
    expect(declaredActionsFor('grid:notes#notes').map((one) => one.id)).toEqual(expect.arrayContaining(['mode:edit', 'mode:preview']));
    expect(declaredActionsFor('notes'), 'nothing on the bare slot id').toEqual([]);

    const el = frame('notes');
    expect(el.dataset['zonePane']).toBe('notes');
    expect(el.dataset['zoneVisible']).toBe('shown');
    expect(FakeObserver.last?.targets.has(el), 'the frame itself is the observed box').toBe(true);
    FakeObserver.last!.report(el, false);
    flushSync();
    expect(el.dataset['zoneVisible']).toBe('hidden');
    FakeObserver.last!.report(el, true);
    flushSync();
    expect(el.dataset['zoneVisible']).toBe('shown');
  });

  test('the title row\'s own control (clear) is declared on the tab header too, so the menu that reads it there offers it', () => {
    app = mount(CellHost, { target: document.body, props: { id: 'activity-log' as SlotId, store: homeLayout } });
    flushSync();
    expect(declaredActionsFor('grid:activity-log#activity-log').map((one) => one.id)).toContain('clear');
    expect(declaredActionsFor('activity-log')).toEqual([]);
  });

  test('the widget reads the rune, on the frame tab header, with no tab-pane context and no box between the frame and the body', () => {
    app = mount(CellInFrame, { target: document.body, props: { slot: 'projects' as SlotId, cell: ZoneProbeCell as unknown as Component<CellProps> } });
    flushSync();
    const stub = document.querySelector<HTMLElement>('[data-stub="projects"]')!;
    expect(stub.dataset['host']).toBe('grid:projects#projects');
    expect(stub.dataset['widgetVisible']).toBe('shown');
    expect(stub.hasAttribute('data-pane-visible'), 'a one-tab zone is not a tab group').toBe(false);
    expect(document.querySelector('.zone-pane'), 'no pane element').toBeNull();

    FakeObserver.last!.report(frame('projects'), false);
    flushSync();
    expect(stub.dataset['widgetVisible']).toBe('hidden');
  });

  test('the keys are the slot\'s own, never a terminal component tab\'s, and the header carries its grid slot', () => {
    expect(gridHeaderId('terminal:row:7')).toBe('grid:terminal:row:7#terminal');
    expect(gridTabKey('terminal:row:7')).not.toContain(':');
    expect(gridHeaderId('activity-log')).toBe('grid:activity-log#activity-log');
    const zone = createGridZone('terminal:row:7', () => 'open');
    const header = zone.headerFor(zone.tabs[0]!.key);
    expect(header.hostId).toBe('grid:terminal:row:7#terminal');
    expect(header.gridSlot).toBe('terminal:row:7');
    expect(zone.spec.menuHost).toBe('grid');
  });

  test('a folded slot is parked', () => {
    let folded = false;
    const zone = createGridZone('notes', () => (folded ? 'collapsed' : 'open'));
    expect(zone.visibility('notes')).toBe('shown');
    folded = true;
    expect(zone.visibility('notes')).toBe('parked');
  });
});
