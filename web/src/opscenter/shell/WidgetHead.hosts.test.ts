/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount, type Component } from 'svelte';

vi.mock('../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../api/auth.svelte')>();
  return { ...real, authFetch: async () => ({ threads: [], next_before: null }) };
});
vi.mock('../lib/viewer-socket', () => ({
  createViewerSocket: () => ({ state: 'connecting', interactive: false, start: () => {}, claimInput: () => null, send: () => false, destroy: () => {} }),
}));
vi.mock('../cells/registry', async (importOriginal) => {
  const real = await importOriginal<typeof import('../cells/registry')>();
  const { default: HeadBarProbe } = await import('./fixtures/HeadBarProbe.svelte');
  const { default: HeadContentProbe } = await import('./fixtures/HeadContentProbe.svelte');
  return {
    ...real,
    entryFor: (slot: string) =>
      slot === 'activity-log' ? { component: HeadBarProbe } : slot.startsWith('terminal:') ? { component: HeadContentProbe } : real.entryFor(slot as never),
  };
});

import PlacementBody from '../../lib/zone-shell/PlacementBody.svelte';
import CellInFrame from './fixtures/CellInFrame.svelte';
import HeadGroupsProbe from './fixtures/HeadGroupsProbe.svelte';
import TimelineCell from '../cells/timeline/Cell.svelte';
import ViewerCell from '../cells/terminal-viewer/Cell.svelte';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { viewport } from '../engine/viewport.svelte';
import { homeLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import type { CellProps } from '../lib/cell';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../lib/i18n/index.svelte';
import { HEADER_OPTION } from './widget-head';

setLocale('en');
installPopoverPolyfill();

let app: object | null = null;
let target: HTMLElement;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  viewport.phone = false;
  viewport.wide = true;
  homeLayout.resetAll();
  document.body.replaceChildren();
});

function show<P extends Record<string, unknown>>(component: Component<P>, props: P): void {
  app = mount(component, { target, props });
  flushSync();
}

const head = (): HTMLElement | null => target.querySelector<HTMLElement>('[data-widget-head]');
const running = CORE_MANIFESTS['core.running-sessions']!;

describe('a header control is drawn where the header is', () => {
  test('a widget bar section with no tick has no header, and the running sessions sort is drawn nowhere (it is a menu item)', () => {
    show(PlacementBody, { host: 'rail', manifest: running, placementKey: 'core.running-sessions' });
    expect(head()).toBeNull();
    expect(target.querySelector('.oc-sort-wrap')).toBeNull();
  });

  test('a drawer card ticked off draws the sort nowhere; ticked on, in its header and not its body', () => {
    show(PlacementBody, { host: 'drawer', manifest: running, options: { [HEADER_OPTION]: false } });
    expect(head()).toBeNull();
    expect(target.querySelector('.oc-sort-wrap')).toBeNull();
    unmount(app!, { outro: false });
    show(PlacementBody, { host: 'drawer', manifest: running });
    expect(head()!.querySelector('.oc-sort-wrap')).not.toBeNull();
    expect(target.querySelector('.dzc-body .oc-sort-wrap')).toBeNull();
  });
});

describe('a drawer card below 1024', () => {
  test('draws no close x and keeps the cell bar in its body, as the grid phone row does', () => {
    show(PlacementBody, { host: 'drawer', manifest: CORE_MANIFESTS['core.activity-log']! });
    expect(head()!.querySelector('[data-head-close]')).not.toBeNull();
    expect(head()!.querySelector('[data-probe-bar]')).not.toBeNull();
    viewport.phone = true;
    viewport.wide = false;
    flushSync();
    expect(head()!.querySelector('[data-head-close]')).toBeNull();
    expect(target.querySelector('.dzc-body [data-probe-bar]')).not.toBeNull();
    expect(head()!.querySelector('[data-corner]')!.classList.contains('oc-frame-corner--tap')).toBe(true);
    expect(head()!.classList.contains('oc-frame-title--phone')).toBe(true);
  });
});

describe('a widget that draws its own head, in a drawer card', () => {
  test('fills the one row with it: no standard name over it and no copy left in the body', () => {
    show(PlacementBody, { host: 'drawer', manifest: CORE_MANIFESTS['core.terminal']!, target: 'ses_probe', options: { [HEADER_OPTION]: false } });
    expect(target.querySelectorAll('[data-widget-head]')).toHaveLength(1);
    expect(head()!.querySelector('[data-probe-own-head]')).not.toBeNull();
    expect(head()!.querySelector('.oc-frame-name')).toBeNull();
    expect(target.querySelector('.dzc-body [data-probe-own-head]')).toBeNull();
  });
});

describe('the order of the groups', () => {
  test('a group that leaves and comes back takes its declared place again', () => {
    show(CellInFrame, { slot: 'closed-sessions' as SlotId, cell: HeadGroupsProbe as unknown as Component<CellProps> });
    const order = (): string[] => [...head()!.querySelectorAll('[data-probe-group]')].map((el) => el.getAttribute('data-probe-group')!);
    expect(order()).toEqual(['first', 'second']);
    target.querySelector<HTMLButtonElement>('[data-probe-toggle]')!.click();
    flushSync();
    expect(order()).toEqual(['second']);
    target.querySelector<HTMLButtonElement>('[data-probe-toggle]')!.click();
    flushSync();
    expect(order()).toEqual(['first', 'second']);
  });
});

describe('a bar the narrow header has no room for', () => {
  test('the timeline picker stays in the body under its width and goes up over it', () => {
    show(CellInFrame, { slot: 'timeline' as SlotId, cell: TimelineCell as Component<CellProps>, width: 360 });
    expect(head()!.querySelector('[data-facet="timeline-session"]')).toBeNull();
    expect(target.querySelector('.oc-tl-top [data-facet="timeline-session"]')).not.toBeNull();
    unmount(app!, { outro: false });
    show(CellInFrame, { slot: 'timeline' as SlotId, cell: TimelineCell as Component<CellProps>, width: 480 });
    expect(head()!.querySelector('[data-facet="timeline-session"]')).not.toBeNull();
  });
});

describe('the terminal viewer on the home grid', () => {
  test('its head row is the frame row, not a second bar under it; below 1024 it is back in the body', () => {
    show(CellInFrame, { slot: 'terminal:ses_viewer_probe' as SlotId, cell: ViewerCell as Component<CellProps> });
    expect(target.querySelectorAll('[data-widget-head]')).toHaveLength(1);
    expect(head()!.querySelector('.oc-tv-head.oc-tv-head--up .oc-tv-name')).not.toBeNull();
    expect(target.querySelector('.oc-tv > .oc-tv-head')).toBeNull();
    viewport.phone = true;
    viewport.wide = false;
    flushSync();
    expect(target.querySelector('.oc-tv > .oc-tv-head')).not.toBeNull();
    expect(head()!.querySelector('.oc-tv-head')).toBeNull();
  });
});
