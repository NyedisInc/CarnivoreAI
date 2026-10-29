/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fakeActive } from './test-support.svelte';

const calls = vi.hoisted(() => [] as { method: string; body: unknown }[]);

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => true, isWidgetDisabled: () => false, storedNode: () => undefined, itemSettings: { refresh: async () => {} } }));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle' && init.method === 'PUT') {
        calls.push({ method: 'PUT', body: JSON.parse(String(init.body)) });
        return { revision: 2, settings: JSON.parse(String(init.body)).settings };
      }
      return { revision: 1, settings: {} };
    },
  };
});

import { layOutRail, follow, mountRails, unmountRails } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';
import './alert-count-sources.svelte';
import { BADGE_DEFAULT, taskManagerPrefs } from '../../cplugs/huddle/task-manager-prefs.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const items = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"][data-node]')].filter((el) => el.closest('[data-level="1"]'));
const rightClickKey = (id: string): void => {
  document.querySelector(`[data-zone-item="${id}"]`)!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
};
const openBranch = (): void => {
  document.querySelector<HTMLElement>('[data-node="count-in-badge"]')!.click();
  flushSync();
};

beforeEach(() => {
  fakeActive.id = 'ses_1';
  taskManagerPrefs.badge = { ...BADGE_DEFAULT };
  calls.length = 0;
  mountRails();
  follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.task-manager', view: 'all' }, { widget: 'core.notes' }] }] });
  flushSync();
  layOutRail('side');
});

afterEach(() => unmountRails());

test('right-clicking the huddle key opens the standard menu with a count in badge branch of the six statuses, questions and reviews ticked by default', () => {
  rightClickKey('core.task-manager');
  const ids = [...document.querySelectorAll<HTMLElement>('[data-level="0"] .acm-item')].map((el) => el.dataset['node']);
  expect(ids).toEqual(expect.arrayContaining(['count-in-badge', 'pop-out', 'show-header', 'close-widget']));
  expect(ids.filter((id) => /^bar-size-/.test(id ?? ''))).toEqual([]);
  expect(ids.indexOf('count-in-badge')).toBe(0);
  expect(document.querySelector('[data-node="count-in-badge"]')!.getAttribute('aria-haspopup')).toBe('menu');
  openBranch();
  expect(items().map((el) => el.textContent?.replace(/\s+/g, ' ').trim())).toEqual(expect.arrayContaining([expect.stringContaining('questions'), expect.stringContaining('scheduled')]));
  expect(items()).toHaveLength(6);
  expect(items().map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'true', 'false', 'false', 'false', 'false']);
});

test('ticking a status stores it through the plugin settings and keeps the whole menu open', async () => {
  rightClickKey('core.task-manager');
  openBranch();
  items()[2]!.click();
  await Promise.resolve(); await Promise.resolve();
  flushSync();
  expect(calls.some((c) => JSON.stringify((c.body as { settings: unknown }).settings) === '{"badgeOpen":true}')).toBe(true);
  expect(items()).toHaveLength(6);
  expect(document.querySelector('[data-level="0"]')).not.toBeNull();
});

test('a key with no narrowable count opens the standard menu without the branch', () => {
  rightClickKey('core.notes');
  expect(document.querySelector('[data-level="0"]')).not.toBeNull();
  expect(document.querySelector('[data-node="count-in-badge"]')).toBeNull();
  expect(items()).toHaveLength(0);
});
