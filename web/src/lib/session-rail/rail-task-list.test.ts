/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import { fakeActive } from './test-support.svelte';

const mk = (id: number, status: string): unknown => ({
  id, list: '1', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: status === 'question' ? 'question' : '', revision: 1, created_seq: id, seq: id,
  deleted: false, status, title: null,
  thread: [{ id: 10 + id, item_id: id, author: 'claude', kind: status === 'question' ? 'question' : 'reply', text: `line ${id}`, answered: false, created_at: 1000 + id, seq: id }],
});
const ITEMS = [mk(1, 'question'), mk(2, 'review'), mk(3, 'working'), mk(4, 'open'), mk(5, 'open')];

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../item-settings/store.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../item-settings/store.svelte')>()),
  widgetSetting: () => true,
  isWidgetDisabled: () => false,
}));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 5, groups: [{ list: '1', name: 'p', project_id: 1, revision: 1, items: ITEMS }] };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '1', name: 'p', project_id: 1, items: 5, open: 5, review: 1, questions: 1, claude_seq: 5 }] };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/swarm/roster') return { agents: [] };
      return { revision: 1, settings: {} };
    },
  };
});
vi.mock('../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import { RAIL_FIELD } from './rail-model';
import { follow, keyIn, mountRails, unmountRails, written } from './rail-test-harness';
import { railSlideout } from './slideout.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import './alert-count-sources.svelte';

setLocale('en');
installPopoverPolyfill();

const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });
const checks = () => [...document.querySelectorAll<HTMLElement>('[data-level="1"] [role="menuitemcheckbox"]')];
const openList = (): void => {
  document.querySelector<HTMLElement>('[data-node="copy-options"]')!.click();
  flushSync();
};
const radio = (id: string): HTMLElement => document.querySelector<HTMLElement>(`[role="menuitemradio"][data-node="${id}"]`)!;
const find = (label: string) => checks().find((item) => item.textContent?.includes(label))!;
const section = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-out-widget="core.task-list"]')!;

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

function rightClick(el: Element, at = { clientX: 40, clientY: 30 }): void {
  el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, ...at }));
  flushSync();
}

const storedOptions = (): unknown => (written.at(-1)!.value as { sections: { items: { options?: unknown }[] }[] }).sections[0]!.items[0]!.options;

beforeEach(() => {
  fakeActive.id = 'ses_1';
  mountRails();
});
afterEach(() => {
  unmountRails();
  document.body.innerHTML = '';
});

describe('the right-click menu of the key', () => {
  test('is the standard menu with a "show in list" branch of the six status checks of the Task Manager badge menu, in its order, all ticked on a new copy', () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list' }));
    rightClick(keyIn('side', 'core.task-list'));
    expect(document.querySelector('[data-node="copy-options"]')?.textContent).toContain('show in list');
    expect(document.querySelector('[data-node="pop-out"]')).not.toBeNull();
    expect(document.querySelector('[data-node="close-widget"], [data-node="remove-widget"]')).not.toBeNull();
    openList();
    expect(checks().map((item) => item.getAttribute('data-node'))).toEqual(['option:st_question', 'option:st_review', 'option:st_open', 'option:st_working', 'option:st_waiting', 'option:st_scheduled']);
    expect(checks().map((item) => item.getAttribute('aria-checked'))).toEqual(Array(6).fill('true'));
    expect(checks().map((item) => item.querySelector('.menu-key')?.textContent?.trim())).toEqual(['q', 'r', 'o', 'w', 'a', 's']);
  });

  test('a tick stays open, is stored on THAT copy alone, and a second tick adds to it', () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list' }, { widget: 'core.task-list', instance: 'i2' }));
    rightClick(keyIn('side', 'core.task-list#i2'));
    openList();
    find('open').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    find('scheduled').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    expect((written.at(-1)!.value as { sections: { items: unknown[] }[] }).sections[0]!.items).toEqual([
      { widget: 'core.task-list' },
      { widget: 'core.task-list', instance: 'i2', options: { st_open: false, st_scheduled: false } },
    ]);
  });
});

describe('the key and the title row', () => {
  test('the key badge is the rows the copy lists', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list', options: { st_open: false } }, { widget: 'core.task-list', instance: 'i2' }));
    keyIn('side', 'core.task-list').click();
    await settle();
    const badge = (id: string): string | null => keyIn('side', id).querySelector('[data-rail-badge]')?.textContent?.trim() ?? null;
    expect(badge('core.task-list')).toBe('3');
    expect(badge('core.task-list#i2')).toBe('5');
  });

  test('with the header ticked the title row carries the count and NO hover keys; density is a radio set of the menu and writes the copy\'s density', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list', options: { show_header: true, st_open: false } }));
    keyIn('side', 'core.task-list').click();
    await settle();
    const head = section().querySelector('[data-widget-head]')!;
    expect(head.querySelector('.oc-frame-count')?.textContent).toContain('3');
    expect(head.querySelector('[data-huddle-list-density], [data-huddle-list-grouping]')).toBeNull();
    expect(section().querySelector('[data-huddle-list-corner]')).toBeNull();
    rightClick(keyIn('side', 'core.task-list'));
    expect([radio('density:compact'), radio('density:full')].map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    expect(radio('density:full').textContent).toContain('two lines');
    radio('density:full').click();
    await settle();
    expect(storedOptions()).toEqual({ show_header: true, st_open: false, density: 'full' });
    expect(section().querySelectorAll('[data-huddle-list-line2]')).toHaveLength(3);
  });

  test('grouping is the other radio set (status or project): it writes the copy\'s grouping and survives with the other options', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list', options: { show_header: true, st_open: false } }));
    keyIn('side', 'core.task-list').click();
    await settle();
    rightClick(keyIn('side', 'core.task-list'));
    expect([radio('group:status'), radio('group:project')].map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    expect(document.querySelector('[data-node="density:compact"]')!.classList.contains('acm-sep')).toBe(true);
    expect(section().querySelectorAll('[data-task-manager-list-head]')[0]?.getAttribute('data-group')).toBe('status');
    radio('group:project').click();
    await settle();
    expect(storedOptions()).toEqual({ show_header: true, st_open: false, group: 'project' });
    expect(section().querySelectorAll('[data-task-manager-list-head]')[0]?.getAttribute('data-group')).toBe('project');
  });

  test('the header is ON by default for this widget (every other bar widget starts without); ticked off the copy draws no row and no hover key, and the menu still has both sets', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list' }, { widget: 'core.task-list', instance: 'i2', options: { show_header: false } }));
    keyIn('side', 'core.task-list').click();
    await settle();
    expect(section().querySelector('[data-widget-head]')).not.toBeNull();
    keyIn('side', 'core.task-list#i2').click();
    await settle();
    const off = document.querySelector<HTMLElement>('[data-rail-out-widget="core.task-list"]')!;
    expect(off.querySelector('[data-widget-head]')).toBeNull();
    expect(off.querySelector('[data-huddle-list-corner], [data-huddle-list-density]')).toBeNull();
    rightClick(keyIn('side', 'core.task-list#i2'));
    expect(['group:status', 'group:project', 'density:compact', 'density:full'].every((id) => radio(id) !== null)).toBe(true);
  });

  test('a right-click anywhere in the open list opens the same menu, and a tick there stores the same way', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-list' }));
    keyIn('side', 'core.task-list').click();
    await settle();
    rightClick(section().querySelector('[data-task-manager-list-row="3"]')!);
    expect(document.querySelector('[data-node="copy-options"]')?.textContent).toContain('show in list');
    openList();
    find('working').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    expect(storedOptions()).toEqual({ st_working: false });
    await settle();
    expect(section().querySelector('[data-task-manager-list-row="3"]')).toBeNull();
    expect(railSlideout.shown('side')).toEqual(['core.task-list']);
  });
});
