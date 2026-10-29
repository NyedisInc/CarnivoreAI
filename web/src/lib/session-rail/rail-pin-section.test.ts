/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ label: 'api', session_row_id: 7, session: { id: 'ses_1' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { BOTTOM_FIELD, follow, keyIn, mountRails, ptr, unmountRails } from './rail-test-harness';
import { railSlideout } from './slideout.svelte';
import { fakeActive } from './test-support.svelte';
import { panelPins } from '../widget-bars/panel-pins.svelte';

const grip = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-grip="bottom"]')!;
const lit = (): string[] => [...document.querySelectorAll<HTMLElement>('[data-rail-grip="bottom"] [data-rail-pin-section]')].map((el) => el.dataset['railPinSection']!);

function clickAt(fraction: number): void {
  grip().getBoundingClientRect = () => ({ left: 0, top: 0, right: 1000, bottom: 8, width: 1000, height: 8, x: 0, y: 0, toJSON: () => ({}) });
  grip().dispatchEvent(ptr('pointerdown', fraction * 1000, 4));
  grip().dispatchEvent(ptr('pointerup', fraction * 1000, 4));
  flushSync();
}

beforeEach(() => {
  localStorage.clear();
  panelPins.reload();
  fakeActive.id = 'ses_1';
  mountRails();
  follow(BOTTOM_FIELD, { v: 2, ratio: 0.5, sections: [{ items: [{ widget: 'core.files' }] }, { items: [{ widget: 'core.notes' }] }] });
  keyIn('bottom', 'core.files').click();
  flushSync();
});
afterEach(() => {
  railSlideout.close();
  unmountRails();
});

describe('a split panel pins one section', () => {
  test('a click over the right half pins only the right section: its stretch of the accent edge', () => {
    expect(lit()).toEqual([]);
    clickAt(0.8);
    expect(panelPins.pinnedRow('bottom', 'core.notes')).toBe(7);
    expect(panelPins.pinnedRow('bottom', 'core.files')).toBeNull();
    expect(lit()).toEqual(['1']);
    clickAt(0.2);
    expect(lit()).toEqual(['0', '1']);
    clickAt(0.8);
    expect(lit()).toEqual(['0']);
    expect(panelPins.pinned('bottom', 'core.notes')).toBe(false);
  });
});
