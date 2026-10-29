/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import { setLocale } from '../i18n/index.svelte';
import { activeFlyout } from './flyout.svelte';
import { tabFlags } from './fixtures/tab-flags.svelte';
import { FLOW_TAB, REPO, flyout, press, rail, railOn, setupRail, settle, teardownRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
registerSwarmFlyout();
import { tabFlyoutId } from './tab-flyouts';
import { MENU_FLYOUT, SESSION_LIST_WIDGET, SWARM_FLYOUT } from './widget-ids';

setLocale('en');

const WIDGETS = path.join(REPO, 'web', 'src', 'lib', 'sidebar-widgets');
const TAP_PX = 44;
const originalWidth = window.innerWidth;

beforeEach(async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 360 });
  await setupRail('mobile');
});

afterEach(async () => {
  await teardownRail();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
});

function phoneBlock(css: string): string {
  const at = css.indexOf('@media (max-width: 700px)');
  if (at < 0) return '';
  const open = css.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}' && (depth -= 1) === 0) return css.slice(open + 1, i);
  }
  return '';
}

test('phone: the rail still applies, every key is there, and a key opens its slide-out', async () => {
  await railOn();
  tabFlags.flow = true;
  await settle();
  const ids = [...rail().querySelectorAll<HTMLElement>('[data-rail-key]')].map((el) => el.dataset.railKey);
  expect(ids.slice(0, 3)).toEqual([SESSION_LIST_WIDGET, SWARM_FLYOUT, tabFlyoutId(FLOW_TAB)]);
  expect(ids.at(-1)).toBe('settings');
  await press(tabFlyoutId(FLOW_TAB));
  expect(activeFlyout()).toBe(tabFlyoutId(FLOW_TAB));
  expect(flyout().classList.contains('sbr-flyout--open')).toBe(true);
});

test('phone: choosing a menu destination closes the slide-out AND the overlay drawer', async () => {
  const closeAfterSwitch = vi.fn();
  vi.stubGlobal('SessionSidebarPin', { closeAfterSwitch });
  await railOn();
  await press(MENU_FLYOUT);
  flyout().querySelector<HTMLButtonElement>('li:not([data-menu-lead]) [data-rail-item]')!.click();
  await settle();
  expect(closeAfterSwitch).toHaveBeenCalled();
  expect(activeFlyout()).toBeNull();
});

test('phone: the keys are tap targets (44px) and the rail column fits them; the slide-out width is never fixed in px', () => {
  const keys = fs.readFileSync(path.join(REPO, 'web', 'src', 'lib', 'zone-shell', 'TabKey.svelte'), 'utf8');
  const keyRule = phoneBlock(keys.slice(keys.indexOf('<style>')));
  const size = Number(/\.sbr-rail__btn\s*\{[^}]*?width:\s*(\d+)px/s.exec(keyRule)?.[1] ?? 0);
  expect(size, 'a rail key is at least a tap target under 700px').toBeGreaterThanOrEqual(TAP_PX);
  const css = fs.readFileSync(path.join(WIDGETS, 'sidebar-rail.css'), 'utf8');
  const column = Number(/--sidebar-rail-w:\s*(\d+)px/.exec(phoneBlock(css))?.[1] ?? 0);
  expect(column, 'the rail column is wider than the key').toBeGreaterThan(size);
  expect(phoneBlock(css)).not.toMatch(/--sidebar-flyout-w:\s*\d+px/);
});
