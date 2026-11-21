/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import { setLocale } from '../i18n/index.svelte';
import { editorSeams } from '../../opscenter/layout-editor/editor.svelte';
import { SWARM_FLYOUT } from './widget-ids';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { flyout, press, railOn, setupRail, teardownRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../plugins/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
registerSwarmFlyout();

setLocale('en');
installPopoverPolyfill();

const realSeams = { ...editorSeams };

beforeEach(async () => {
  await setupRail();
  editorSeams.wide = () => true;
  editorSeams.page = () => 'home' as never;
  editorSeams.store = () => ({}) as never;
});

afterEach(async () => {
  Object.assign(editorSeams, realSeams);
  await teardownRail();
});

function corner(): HTMLButtonElement | null {
  return flyout().querySelector<HTMLButtonElement>('.sbr-flyout__title [data-corner]');
}

/** A right-click on an element the way the page receives it. Inputs: el. Output: the event. */
function rightClick(el: Element): MouseEvent {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 });
  el.dispatchEvent(event);
  flushSync();
  return event;
}

test('the title row\'s top-left icon is the title strip\'s menu button, not a bare icon', async () => {
  await railOn();
  await press(SWARM_FLYOUT);
  const icon = corner();
  expect(icon, 'the icon is a CornerMenu button').not.toBeNull();
  expect(icon!.getAttribute('aria-haspopup')).toBe('menu');
});

test('a right-click on it opens the widget menu in place of the browser\'s, and the pin is not in it', async () => {
  await railOn();
  await press(SWARM_FLYOUT);
  const icon = corner()!;
  expect(document.querySelector('.acm-menu')).toBeNull();
  const event = rightClick(icon);
  expect(event.defaultPrevented).toBe(true);
  const menu = document.querySelector('.acm-menu');
  expect(menu).not.toBeNull();
  expect(menu!.querySelector('[data-node="edit-layout"]'), 'the menu drew its nodes').not.toBeNull();
  expect(menu!.querySelector('[data-node="pin-bar"]'), 'a pin is the rail\'s own menu, never a widget\'s').toBeNull();
});

test('the focused icon takes the same event (Shift+F10 in a browser)', async () => {
  await railOn();
  await press(SWARM_FLYOUT);
  const icon = corner()!;
  icon.focus();
  expect(document.activeElement).toBe(icon);
  rightClick(document.activeElement!);
  expect(document.querySelector('.acm-menu')).not.toBeNull();
});

test('a page with nothing to edit still offers remove widget, written once, and no edit layout', async () => {
  Object.assign(editorSeams, realSeams);
  editorSeams.wide = () => false;
  await railOn();
  await press(SWARM_FLYOUT);
  const icon = corner()!;
  expect(icon, 'the icon is a live menu button, not inert').not.toBeNull();
  rightClick(icon);
  const menu = document.querySelector('.acm-menu')!;
  expect(menu.querySelector('[data-node="edit-layout"]')).toBeNull();
  const remove = menu.querySelector<HTMLElement>('[data-node="remove-widget"]');
  expect(remove, 'remove widget is offered outside edit layout').not.toBeNull();
  const writes: unknown[] = [];
  const g = globalThis as unknown as { PreferenceBridge?: unknown };
  g.PreferenceBridge = { read: (_f: string, fb: () => unknown) => fb(), write: async (f: string, v: unknown, local: () => void) => { writes.push([f, v]); local(); return { status: 'committed' }; }, follow: () => () => {} };
  remove!.click();
  flushSync();
  await Promise.resolve();
  expect(writes).toEqual([['rail_hidden_icons', [SWARM_FLYOUT]]]);
  delete g.PreferenceBridge;
});
