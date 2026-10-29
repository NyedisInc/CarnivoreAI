/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
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

import './alert-count-sources.svelte';
import { layOutRail, follow, mountRails, unmountRails } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';

const badge = (widget: string): string | null =>
  document.querySelector(`[data-zone-item="${widget}"] [data-rail-badge]`)?.textContent ?? null;

const ok = (n: number) => ({ state: 'ok', files: Array.from({ length: n }, (_, i) => ({ path: `f${i}`, kind: 'modified' })), truncated: 0 });

function showRail(data: unknown): void {
  fakeActive.id = 'ses_1';
  git.data = data;
  mountRails();
  follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.files' }, { widget: 'core.notes' }] }] });
  flushSync();
  layOutRail('side');
}

afterEach(() => unmountRails());

test('the files key shows the changed-files count; notes shows nothing', () => {
  showRail(ok(3));
  expect(badge('core.files')).toBe('3');
  expect(badge('core.notes')).toBeNull();
});

test('a clean tree draws no bubble', () => {
  showRail(ok(0));
  expect(badge('core.files')).toBeNull();
});

test('a read not done draws no bubble', () => {
  showRail(null);
  expect(badge('core.files')).toBeNull();
});
