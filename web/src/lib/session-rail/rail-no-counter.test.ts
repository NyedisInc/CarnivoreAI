/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fakeActive } from './test-support.svelte';

const git = vi.hoisted(() => ({ data: null as unknown }));

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => undefined, isWidgetDisabled: () => false }));
vi.mock('../../opscenter/api/session-git.svelte', () => ({
  sessionGit: () => ({ get data() { return git.data; } }),
  releaseSessionGit: () => {},
}));

import { layOutRail, follow, mountRails, unmountRails } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';

afterEach(() => unmountRails());

test('the files key draws no counter while its session has three changed files', () => {
  fakeActive.id = 'ses_1';
  git.data = { state: 'ok', files: [0, 1, 2].map((i) => ({ path: `f${i}`, kind: 'modified' })), truncated: 0 };
  mountRails();
  follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.files' }] }] });
  flushSync();
  layOutRail('side');
  const key = document.querySelector<HTMLElement>('[data-zone-item="core.files"]');
  expect(key, 'the files key is drawn').not.toBeNull();
  expect(key!.querySelector('svg'), 'its icon stays').not.toBeNull();
  expect(key!.querySelector('[data-rail-badge], .zone-badge'), 'no counter node').toBeNull();
  expect(key!.textContent ?? '', 'no digit on the key').not.toMatch(/\d/);
});
