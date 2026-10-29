/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ label: 'api', session_row_id: 7, session: { id: 'ses_1' } }, { label: 'beta', session_row_id: 8, session: { id: 'ses_2' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD } from './rail-model';
import { railSlideout } from './slideout.svelte';
import { panelPins } from '../widget-bars/panel-pins.svelte';
import { fakeActive } from './test-support.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, ptr, unmountRails } from './rail-test-harness';

const locked = (): boolean => document.querySelector('[data-rail-pin-section]') !== null;
const grip = (edge: 'side' | 'bottom'): HTMLElement => document.querySelector<HTMLElement>(`[data-rail-grip="${edge}"]`)!;
const panel = (edge: 'side' | 'bottom'): HTMLElement => document.querySelector<HTMLElement>(`[data-rail-edge="${edge}"]`)!;
const key = (event: string, target: Element, k: string): void => void target.dispatchEvent(new KeyboardEvent(event, { key: k, bubbles: true, cancelable: true }));

beforeEach(() => {
  localStorage.clear();
  mountRails();
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.notes' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
  keyIn('side', 'core.files').click();
  flushSync();
});
afterEach(() => {
  railSlideout.close();
  unmountRails();
});

describe('the inner edge', () => {
  test('a press and release within 3px toggles the pin and keeps the size; clicking again unpins', () => {
    const before = panel('side').dataset['railExtent'];
    expect(locked()).toBe(false);
    grip('side').dispatchEvent(ptr('pointerdown', 900, 200));
    grip('side').dispatchEvent(ptr('pointermove', 898, 201));
    grip('side').dispatchEvent(ptr('pointerup', 898, 201));
    flushSync();
    expect(locked()).toBe(true);
    expect(panelPins.pinnedRow('side', 'core.files')).toBe(7);
    expect(grip('side').getAttribute('aria-label')).toBe('pinned on api, click to unpin');
    expect(panel('side').dataset['railExtent']).toBe(before);
    grip('side').dispatchEvent(ptr('pointerdown', 900, 200));
    grip('side').dispatchEvent(ptr('pointerup', 900, 200));
    flushSync();
    expect(locked()).toBe(false);
    expect(grip('side').getAttribute('aria-label')).toBe('drag to resize, click to pin');
  });

  test('a 4px move resizes and never toggles, on either edge', () => {
    const before = Number(panel('side').dataset['railExtent']);
    grip('side').dispatchEvent(ptr('pointerdown', 900, 200));
    grip('side').dispatchEvent(ptr('pointermove', 896, 200));
    grip('side').dispatchEvent(ptr('pointerup', 896, 200));
    flushSync();
    expect(Number(panel('side').dataset['railExtent'])).toBe(before + 4);
    expect(panelPins.pinned('side')).toBe(false);

    keyIn('bottom', 'core.notes').click();
    flushSync();
    const tall = Number(panel('bottom').dataset['railExtent']);
    grip('bottom').dispatchEvent(ptr('pointerdown', 400, 500));
    grip('bottom').dispatchEvent(ptr('pointermove', 400, 440));
    grip('bottom').dispatchEvent(ptr('pointerup', 400, 440));
    flushSync();
    expect(Number(panel('bottom').dataset['railExtent'])).toBe(tall + 60);
    expect(panelPins.pinned('bottom')).toBe(false);
  });

  test('Enter and Space toggle the pin, a double click does nothing, and closing the panel clears the pin', () => {
    key('keydown', grip('side'), 'Enter');
    flushSync();
    expect(panelPins.pinned('side')).toBe(true);
    key('keydown', grip('side'), ' ');
    flushSync();
    expect(panelPins.pinned('side')).toBe(false);
    const before = panel('side').dataset['railExtent'];
    grip('side').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    flushSync();
    expect(panel('side').dataset['railExtent']).toBe(before);
    expect(panelPins.pinned('side')).toBe(false);
    key('keydown', grip('side'), 'Enter');
    keyIn('side', 'core.files').click();
    flushSync();
    expect(panelPins.pinned('side')).toBe(false);
  });

  test('Escape from inside a terminal keeps the panel; Escape from its body closes it', () => {
    const body = panel('side').querySelector<HTMLElement>('[data-rail-body]') ?? panel('side');
    const term = document.createElement('div');
    term.className = 'xterm';
    const inner = document.createElement('textarea');
    term.appendChild(inner);
    body.appendChild(term);
    key('keydown', inner, 'Escape');
    flushSync();
    expect(railSlideout.shown('side')).toEqual(['core.files']);
    key('keydown', body, 'Escape');
    flushSync();
    expect(railSlideout.shown('side')).toEqual([]);
  });

  test('neither edge has a title row', () => {
    keyIn('bottom', 'core.notes').click();
    flushSync();
    for (const edge of ['side', 'bottom'] as const) {
      expect(panel(edge).querySelector('.rail-out__bar, [data-rail-close], .rail-out__title')).toBeNull();
      expect(panel(edge).querySelector('[data-rail-out-section]')?.getAttribute('role')).toBe('group');
    }
  });
});

describe('the inner edge, edge cases', () => {
  test('a pin with no listed agent is refused', () => {
    fakeActive.id = 'ses_unlisted';
    flushSync();
    key('keydown', grip('side'), 'Enter');
    flushSync();
    expect(panelPins.pinned('side')).toBe(false);
    fakeActive.id = 'ses_1';
    flushSync();
    key('keydown', grip('side'), 'Enter');
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.files')).toBe(7);
  });

  test('a lost pointer capture ends the drag, so a later release toggles nothing', () => {
    const before = panel('side').dataset['railExtent'];
    grip('side').dispatchEvent(ptr('pointerdown', 900, 200));
    grip('side').dispatchEvent(new Event('lostpointercapture'));
    grip('side').dispatchEvent(ptr('pointerup', 900, 200));
    flushSync();
    expect(panel('side').dataset['railExtent']).toBe(before);
    expect(locked()).toBe(false);
  });
});
