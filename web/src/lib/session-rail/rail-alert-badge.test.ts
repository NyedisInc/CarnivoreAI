/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fakeActive, fakeBadge } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../item-settings/store.svelte', async () => {
  const { fakeBadge: badge } = await import('./test-support.svelte');
  return { widgetSetting: () => badge.show, isWidgetDisabled: () => false };
});

import { registerAlertCount } from './alert-counts';
import { layOutRail } from './rail-test-harness';
import { follow, mountRails, unmountRails } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';

const badge = (widget: string): string | null =>
  document.querySelector(`[data-zone-item="${widget}"] [data-rail-badge]`)?.textContent ?? null;

beforeEach(() => {
  fakeActive.id = 'ses_1';
  fakeBadge.count = 3;
  fakeBadge.show = true;
  registerAlertCount('core.task-manager-all', { read: () => fakeBadge.count });
  mountRails();
  follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.task-manager', view: 'all' }, { widget: 'core.notes' }] }] });
  flushSync();
  layOutRail('side');
});

afterEach(() => unmountRails());

test('a widget publishing 3 shows 3 on its key; notes, with no source, shows nothing', () => {
  expect(badge('core.task-manager')).toBe('3');
  expect(badge('core.notes')).toBeNull();
});

test('turning the widget option off hides the badge, and back on shows it', () => {
  fakeBadge.show = false;
  flushSync();
  expect(badge('core.task-manager')).toBeNull();
  fakeBadge.show = true;
  flushSync();
  expect(badge('core.task-manager')).toBe('3');
});

test('zero and unknown show nothing, and a large count reads 99+', () => {
  fakeBadge.count = 0;
  flushSync();
  expect(badge('core.task-manager')).toBeNull();
  fakeBadge.count = null;
  flushSync();
  expect(badge('core.task-manager')).toBeNull();
  fakeBadge.count = 250;
  flushSync();
  expect(badge('core.task-manager')).toBe('99+');
});
