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

import { tooltipTargetFor } from '../tooltip/tooltip';
import { RAIL_FIELD } from './rail-model';
import { railOutSizes } from './rail-out-size.svelte';
import { railSlideout } from './slideout.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from './rail-test-harness';

beforeEach(() => {
  mountRails();
  localStorage.clear();
  railSlideout.reload();
  railOutSizes.reload();
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }, { widget: 'core.ledger' }] });
});
afterEach(() => unmountRails());

test('a rail key carries a tooltip target while closed and while its slide-out is open, on both rails', () => {
  for (const [edge, widget] of [['side', 'core.changes'], ['bottom', 'core.task-manager']] as const) {
    const key = keyIn(edge, widget);
    expect(key.getAttribute('aria-expanded')).toBe('false');
    expect(tooltipTargetFor(key), `${widget} closed`).toBe(key);
    key.click();
    flushSync();
    expect(key.getAttribute('aria-expanded')).toBe('true');
    expect(tooltipTargetFor(key), `${widget} open`).toBe(key);
    expect(key.getAttribute('title')).toBeTruthy();
  }
});
