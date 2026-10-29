/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import { activeFlyout, closeFlyout } from '../sidebar-widgets/flyout.svelte';
import { MENU_FLYOUT, SESSION_LIST_WIDGET } from '../sidebar-widgets/widget-ids';
import { leftRailWidgets, leftRailZone, setDrawnFlyout } from './left-rail-zone.svelte';

beforeEach(() => registerCoreSidebarWidgets());
afterEach(() => {
  closeFlyout();
  setDrawnFlyout(null);
});

test('the tabs are the rail keys, one zone for both rails', () => {
  const zone = leftRailZone();
  expect(zone.tabs.map((tab) => tab.key)).toEqual(leftRailWidgets().map((widget) => widget.id));
  expect(zone.tabs.map((tab) => tab.key)).toEqual([MENU_FLYOUT, SESSION_LIST_WIDGET]);
  expect(leftRailZone(), 'made once').toBe(zone);
  expect(zone.spec.strip).toBe('keys');
});

test('select presses the rail: it opens the slide-out, the panel opens, and a second select closes it', () => {
  const zone = leftRailZone();
  expect(zone.spec.panel()).toBe('closed');
  zone.spec.select(MENU_FLYOUT);
  flushSync();
  expect(activeFlyout()).toBe(MENU_FLYOUT);
  expect(zone.spec.panel()).toBe('open');
  expect(zone.active?.key).toBe(MENU_FLYOUT);
  expect(zone.visibility(MENU_FLYOUT)).toBe('shown');
  zone.spec.select(MENU_FLYOUT);
  flushSync();
  expect(activeFlyout()).toBeNull();
});

test('the slide-out being drawn stays the active tab through the close, but its panel is closed so it is parked', () => {
  const zone = leftRailZone();
  zone.spec.select(MENU_FLYOUT);
  setDrawnFlyout(MENU_FLYOUT);
  zone.spec.select(MENU_FLYOUT);
  flushSync();
  expect(activeFlyout()).toBeNull();
  expect(zone.active?.key, 'still drawn while it slides shut').toBe(MENU_FLYOUT);
  expect(zone.visibility(MENU_FLYOUT)).toBe('parked');
  setDrawnFlyout(null);
  expect(zone.active).toBeNull();
});
