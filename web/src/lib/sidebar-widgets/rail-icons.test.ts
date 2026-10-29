/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (p: string) => (p.includes('sessions') ? [] : {}),
}));

import { setLocale } from '../i18n/index.svelte';
import { saveMenuOrder } from '../drawer-tabs/menu-order.svelte';
import { PREFERENCE_FIELD, setRailIconHidden, shownIcons } from './rail-icons.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { RAIL_SPLIT } from './rail-zones';
import { rail, railOn, setupRail, settle, teardownRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
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

const badge = (id: string): HTMLButtonElement => rail().querySelector<HTMLElement>(`[data-rail-key="${id}"]`)!.closest('[data-edit-cell]')!.querySelector<HTMLButtonElement>('[data-edit-badge]')!;

const keys = (): (string | undefined)[] => [...rail().querySelectorAll<HTMLElement>('[data-rail-key]')].map((el) => el.dataset.railKey);

test('default: nothing stored shows every icon in the default order, and nothing is written', async () => {
  await railOn();
  const all = keys();
  expect(all.slice(0, 2)).toEqual(['core.session-list', 'core.swarm']);
  expect(all.at(-1)).toBe('settings');
  expect(all.indexOf('docs')).toBeLessThan(all.indexOf('changelog'));
  expect(PREFERENCE_FIELD in store).toBe(false);
  expect(rail().querySelector('[data-hidden]')).toBeNull();
});

test('edit layout: the badge hides it and saves; leaving edit mode shows the rail without it; pressing again shows it', async () => {
  await railOn();
  const before = keys();
  layoutEditor.active = true;
  await settle();
  expect(keys()).toEqual(before);
  badge('docs').click();
  await settle();
  expect(store[PREFERENCE_FIELD]).toEqual(['docs']);
  expect(keys(), 'edit mode still draws the hidden icon, dimmed').toContain('docs');
  expect(rail().querySelector('[data-hidden] [data-rail-key="docs"]')).not.toBeNull();
  expect(badge('docs').dataset.state).toBe('hidden');
  layoutEditor.active = false;
  await settle();
  expect(keys()).toEqual(before.filter((id) => id !== 'docs'));
  layoutEditor.active = true;
  await settle();
  badge('docs').click();
  await settle();
  expect(store[PREFERENCE_FIELD], 'a fully shown rail goes back to absent').toBeNull();
});

test('one edit mode: outside edit layout there is no badge and no dashed cell; inside, every icon has both and a press still opens it', async () => {
  await railOn();
  expect(rail().querySelector('[data-edit-cell]')).toBeNull();
  layoutEditor.active = true;
  await settle();
  const n = rail().querySelectorAll('[data-rail-key]').length;
  expect(rail().querySelectorAll('[data-edit-cell] [data-edit-badge]')).toHaveLength(n);
  expect(badge('docs').getAttribute('aria-label')).toBe('hide documentation');
  rail().querySelector<HTMLElement>('[data-rail-key="docs"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  await settle();
  expect(PREFERENCE_FIELD in store, 'pressing the icon itself hides nothing').toBe(false);
});

test('two zones: by default the bottom zone holds documentation, changelog, settings; Alt+ArrowUp from settings crosses up and the order is one stored value', async () => {
  await railOn();
  const zone = (name: string): (string | undefined)[] => [...rail().querySelectorAll<HTMLElement>(`[data-rail-zone="${name}"] [data-rail-key]`)].map((el) => el.dataset.railKey);
  expect(zone('bottom')).toEqual(['docs', 'changelog', 'settings']);
  expect('menu_order' in store, 'nothing is written until the user moves something').toBe(false);
  layoutEditor.active = true;
  await settle();
  const bottomFirst = rail().querySelector<HTMLElement>('[data-rail-key="docs"]')!;
  bottomFirst.focus();
  bottomFirst.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', altKey: true, bubbles: true, cancelable: true }));
  await settle();
  expect(zone('top').at(-1)).toBe('docs');
  expect(zone('bottom')).toEqual(['changelog', 'settings']);
  expect(store.menu_order as string[]).toContain(RAIL_SPLIT);
  for (const id of ['changelog', 'settings']) {
    rail().querySelector<HTMLElement>(`[data-rail-key="${id}"]`)!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', altKey: true, bubbles: true, cancelable: true }));
    await settle();
  }
  expect(zone('top').slice(-3)).toEqual(['docs', 'changelog', 'settings']);
  expect(zone('bottom')).toEqual([]);
});

test('order: the saved order moves an icon inside its group; a hidden id the rail does not know changes nothing', async () => {
  await railOn();
  const before = keys();
  saveMenuOrder(['changelog', 'docs']);
  await setRailIconHidden('an-icon-that-is-gone', true);
  await settle();
  const after = keys();
  expect(after.indexOf('changelog')).toBeLessThan(after.indexOf('docs'));
  expect([...after].sort()).toEqual([...before].sort());
});

test('shownIcons: an icon the saved layout does not name is shown, edit mode shows all', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'new' }];
  expect(shownIcons(items, ['b'], false).map((i) => i.id)).toEqual(['a', 'new']);
  expect(shownIcons(items, ['b'], true).map((i) => i.id)).toEqual(['a', 'b', 'new']);
  expect(shownIcons(items, [], false)).toHaveLength(3);
});
