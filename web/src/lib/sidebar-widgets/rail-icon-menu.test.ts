/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { activeFlyout } from './flyout.svelte';
import { MENU_FLYOUT } from './widget-ids';
import { rail, railOn, settle, setupRail, teardownRail, unpinRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../plugins/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
registerSwarmFlyout();

setLocale('en');

beforeEach(async () => {
  await setupRail();
});

afterEach(teardownRail);

test('pinned: every menu row is an icon-only key with its name on the cell, agents first, swarm second, settings last; unpinned: a hover brings out the full menu in that order', async () => {
  await railOn();
  const cells = [...rail().querySelectorAll<HTMLElement>('[data-dock-name]')];
  const names = cells.map((c) => c.dataset.dockName);
  expect(names.slice(0, 2)).toEqual(['agents', 'swarm']);
  expect(names.at(-2), 'settings is the last row, the pin after it').toBe('settings');
  expect(names.at(-1)).toBe('unpin rail');
  for (const key of rail().querySelectorAll<HTMLElement>('[data-rail-key]')) {
    expect(key.textContent?.replace(/\d+/g, '').trim(), `${key.dataset.railKey} shows an icon, no words`).toBe('');
    expect(key.querySelector('svg'), `${key.dataset.railKey} has its icon`).not.toBeNull();
    expect(key.getAttribute('aria-label')?.length, 'and a spoken name').toBeGreaterThan(0);
  }

  await unpinRail();
  expect(rail().querySelector('[data-rail-key]'), 'unpinned: no icon keys').toBeNull();
  const shell = rail().querySelector('.sbr-shell')!;
  shell.dispatchEvent(Object.assign(new MouseEvent('pointerenter'), { pointerType: 'mouse' }));
  flushSync();
  await settle();
  expect(activeFlyout()).toBe(MENU_FLYOUT);
  const rows = [...document.querySelectorAll<HTMLElement>('#session-sidebar-flyout [data-rail-item]')];
  const text = (el: HTMLElement): string => el.textContent?.trim().toLowerCase() ?? '';
  expect(rows.slice(0, 2).map(text).map((s) => s.split(/\s+/)[0])).toEqual(['agents', 'swarm']);
  expect(text(rows.at(-1)!), 'settings is the last row').toContain('settings');
  const settingsLi = rows.at(-1)!.closest('li')!;
  const pin = settingsLi.querySelector<HTMLElement>('[data-bar-pin]');
  expect(pin, 'the pin lives in the settings row').not.toBeNull();
  expect(rows.at(-1)!.contains(pin), 'not inside the settings button').toBe(false);
  expect(pin!.getAttribute('aria-label')?.length, 'and has a spoken name').toBeGreaterThan(0);
  expect(document.querySelector('#session-sidebar-bar-slot [data-bar-action="rail-pin"]'), 'the footer has no pin').toBeNull();
  expect(settingsLi.closest('ul')!.parentElement!.lastElementChild, 'settings is the last block of the menu').toBe(settingsLi.closest('ul'));
});
