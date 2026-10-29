/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD } from './rail-model';
import { railOutSizes } from './rail-out-size.svelte';
import { railSlideout } from './slideout.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, remountRails, unmountRails } from './rail-test-harness';

const panelFor = (edge: string): HTMLElement | null => document.querySelector<HTMLElement>(`[data-rail-slideout][data-rail-edge="${edge}"]`);

beforeEach(() => {
  mountRails();
  localStorage.clear();
  railSlideout.reload();
  railOutSizes.reload();
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }, { widget: 'core.ledger' }] });
});
afterEach(() => unmountRails());

test('opening the bottom slide-out leaves the side one out, and each closes alone', () => {
  keyIn('side', 'core.changes').click();
  keyIn('bottom', 'core.task-manager').click();
  flushSync();
  expect(panelFor('side')).not.toBeNull();
  expect(panelFor('bottom')).not.toBeNull();
  expect(railSlideout.shown('side')).toEqual(['core.changes']);
  expect(railSlideout.shown('bottom')).toEqual(['core.task-manager']);

  keyIn('side', 'core.changes').click();
  flushSync();
  expect(railSlideout.shown('side')).toEqual([]);
  expect(railSlideout.shown('bottom')).toEqual(['core.task-manager']);
  expect(panelFor('bottom')).not.toBeNull();

  railSlideout.close('bottom');
  expect(railSlideout.shown('bottom')).toEqual([]);
});

test('both rails push the grid at once and both come back after a refresh', () => {
  keyIn('side', 'core.files').click();
  keyIn('bottom', 'core.ledger').click();
  flushSync();
  expect(document.getElementById('session-widget-rail')?.style.marginLeft).not.toBe('');
  expect(document.getElementById('session-widget-rail-bottom')?.style.marginTop).not.toBe('');

  unmountRails();
  railSlideout.reload();
  remountRails();
  expect(railSlideout.shown('side')).toEqual(['core.files']);
  expect(railSlideout.shown('bottom')).toEqual(['core.ledger']);
  expect(railSlideout.restoring).toBe(true);
});
