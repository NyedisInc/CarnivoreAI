/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (p: string) => (p.includes('sessions') ? [] : {}),
}));

import { flushSync, mount, unmount } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { PREFERENCE_FIELD, RAIL_PIN_ID } from './rail-icons.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { rail, railOn, setupRail, settle, teardownRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';
import MiniRail from '../mini-rail/MiniRail.svelte';

registerSwarmFlyout();
setLocale('en');

let store: Record<string, unknown>;

beforeEach(async () => {
  store = await setupRail();
  (globalThis as Record<string, unknown>).PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field === 'widget_bars' ? { v: 1, rail: { mode: 'pinned' } } : field in store ? store[field] : fallback()),
    write: async (field: string, value: unknown, local: () => void) => { store[field] = value; local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  layoutEditor.active = false;
});

afterEach(teardownRail);

const pin = (): HTMLElement | null => rail().querySelector<HTMLElement>('[data-bar-pin]');
const pinBadge = (): HTMLButtonElement | null => pin()?.closest('[data-edit-cell]')?.querySelector<HTMLButtonElement>('[data-edit-badge]') ?? null;

test('outside edit layout the pin is drawn with no badge; in edit layout it wears the badge', async () => {
  await railOn();
  expect(pin()).not.toBeNull();
  expect(pinBadge()).toBeNull();
  layoutEditor.active = true;
  await settle();
  expect(pinBadge()).not.toBeNull();
  expect(pinBadge()!.dataset.state).toBe('shown');
});

test('the badge hides the pin and stores it in rail_hidden_icons; it stays drawn (dimmed) while editing and is gone after', async () => {
  await railOn();
  layoutEditor.active = true;
  await settle();
  pinBadge()!.click();
  await settle();
  expect(store[PREFERENCE_FIELD]).toEqual([RAIL_PIN_ID]);
  expect(pinBadge()!.dataset.state).toBe('hidden');
  layoutEditor.active = false;
  await settle();
  expect(pin()).toBeNull();
  layoutEditor.active = true;
  await settle();
  pinBadge()!.click();
  await settle();
  expect(store[PREFERENCE_FIELD], 'shown again: back to absent').toBeNull();
});

test('a hidden pin never hides the closed drawer\'s reopen key, so a closed drawer can always be reopened', async () => {
  store[PREFERENCE_FIELD] = [RAIL_PIN_ID];
  const open = vi.fn();
  (globalThis as unknown as { SessionSidebar: unknown }).SessionSidebar = { open };
  document.body.classList.add('session-sidebar-railed');
  const target = document.createElement('div');
  document.body.append(target);
  const handle = mount(MiniRail, { target });
  flushSync();
  await settle();
  const key = target.querySelector<HTMLButtonElement>('[data-rail="open"]');
  expect(key).not.toBeNull();
  expect(key!.closest('[data-edit-cell]')).toBeNull();
  layoutEditor.active = true;
  await settle();
  expect(target.querySelector<HTMLButtonElement>('[data-rail="open"]')).not.toBeNull();
  target.querySelector<HTMLButtonElement>('[data-rail="open"]')!.click();
  expect(open).toHaveBeenCalledTimes(1);
  await unmount(handle);
  document.body.classList.remove('session-sidebar-railed');
});
