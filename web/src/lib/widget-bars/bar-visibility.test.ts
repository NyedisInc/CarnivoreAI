/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD, RAIL_SPECS } from '../session-rail/rail-model';
import { railOutSizes } from '../session-rail/rail-out-size.svelte';
import { railSlideout } from '../session-rail/slideout.svelte';
import { AUTOHIDE_BARS, BOTTOM_FIELD, follow, keyIn, mountRails, remountRails, unmountRails } from '../session-rail/rail-test-harness';
import { barLead } from './bar-lead.svelte';
import { widgetBars } from './bar-settings.svelte';
import { RETRACT_MS } from './bar-state';
import { matchGolden } from '../zone-shell/fixtures/golden';

const nav = (edge: 'side' | 'bottom'): HTMLElement => document.getElementById(RAIL_SPECS[edge].id)!;
const stateOf = (edge: 'side' | 'bottom'): string | undefined => nav(edge).dataset['barState'];
const track = (edge: 'side' | 'bottom'): string => nav(edge).style.getPropertyValue('--rail-track');
const enter = (el: Element): void => { el.dispatchEvent(Object.assign(new MouseEvent('pointerenter'), { pointerType: 'mouse' })); flushSync(); };
const leave = (el: Element): void => { el.dispatchEvent(Object.assign(new MouseEvent('pointerleave'), { pointerType: 'mouse' })); flushSync(); };
const advance = (ms: number): void => { vi.advanceTimersByTime(ms); flushSync(); };
const open = (edge: 'side' | 'bottom'): void => {
  enter(nav(edge));
  nav(edge).querySelector('[data-bar-handle]')!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  flushSync();
};

beforeEach(() => {
  vi.useFakeTimers();
  mountRails();
  localStorage.clear();
  railSlideout.reload();
  railOutSizes.reload();
  barLead.edge = null;
  follow('widget_bars', null);
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }] });
});
afterEach(() => {
  unmountRails();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('a bar is a 10px handle; a hover or a click slides it out OVER the terminals and back 300 ms after the pointer leaves', () => {
  expect(stateOf('side')).toBe('handle');
  expect(track('side')).toBe('10px');
  expect(nav('side').querySelector('[data-bar-handle]')).not.toBeNull();
  expect((nav('side').querySelector('[data-rail-layer]') as HTMLElement).inert).toBe(true);
  open('side');
  expect(stateOf('side')).toBe('peek');
  expect(track('side')).toBe('10px');
  expect(nav('side').dataset['railPush']).toBe('0');
  expect((nav('side').querySelector('[data-rail-layer]') as HTMLElement).inert).toBe(false);
  expect(nav('side').querySelector('[data-bar-pin]'), 'the pin icon is drawn while out').not.toBeNull();

  leave(nav('side'));
  advance(RETRACT_MS - 1);
  expect(stateOf('side')).toBe('peek');
  advance(1);
  expect(stateOf('side')).toBe('handle');
});

test('a key opens its panel in flow (one grid change), the bar holds while it is open, and retracts 300 ms after it closes', () => {
  open('side');
  keyIn('side', 'core.files').click();
  flushSync();
  expect(stateOf('side')).toBe('held');
  expect(track('side')).toBe('');
  leave(nav('side'));
  advance(5000);
  expect(stateOf('side')).toBe('held');
  expect(Number(nav('side').dataset['railPush'])).toBeGreaterThan(0);

  keyIn('side', 'core.files').click();
  flushSync();
  expect(stateOf('side')).toBe('peek');
  expect(track('side')).toBe('10px');
  advance(RETRACT_MS);
  expect(stateOf('side')).toBe('handle');
});

function focusKey(visible: boolean): void {
  const key = keyIn('side', 'core.files');
  const matches = key.matches.bind(key);
  key.matches = (selector: string): boolean => (selector === ':focus-visible' ? visible : matches(selector));
  key.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
}

test('focus inside holds the bar out; the handle alone does not', () => {
  open('side');
  focusKey(true);
  leave(nav('side'));
  advance(5000);
  expect(stateOf('side')).toBe('peek');
  keyIn('side', 'core.files').dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
  advance(RETRACT_MS);
  expect(stateOf('side')).toBe('handle');
  nav('side').querySelector('[data-bar-handle]')!.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
  advance(RETRACT_MS);
  expect(stateOf('side')).toBe('handle');
});

test('a mouse click that leaves focus on a key does not hold the bar once the mouse leaves', () => {
  open('side');
  focusKey(false);
  leave(nav('side'));
  advance(RETRACT_MS);
  expect(stateOf('side')).toBe('handle');
});

test('Escape inside a peeking bar retracts it and puts focus on the handle', () => {
  open('side');
  keyIn('side', 'core.files').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(stateOf('side')).toBe('handle');
  expect(document.activeElement).toBe(nav('side').querySelector('[data-bar-handle]'));
});

test('Enter on the handle peeks and focuses the first key; a touch tap on it toggles the peek', async () => {
  const handle = nav('side').querySelector<HTMLElement>('[data-bar-handle]')!;
  handle.click();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  expect(stateOf('side')).toBe('peek');
  expect(document.activeElement).toBe(keyIn('side', 'core.changes'));

  const bottom = nav('bottom').querySelector<HTMLElement>('[data-bar-handle]')!;
  bottom.dispatchEvent(Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerType: 'touch' }));
  bottom.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  flushSync();
  expect(stateOf('bottom')).toBe('peek');
  advance(5000);
  expect(stateOf('bottom')).toBe('peek');
  bottom.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  flushSync();
  expect(stateOf('bottom')).toBe('handle');
});

test('a click on the border does nothing: it never hides a peeking bar and never unpins a pinned one', async () => {
  const set = vi.spyOn(widgetBars, 'set').mockResolvedValue('committed');
  open('side');
  nav('side').querySelector<HTMLElement>('[data-bar-edge]')!.click();
  flushSync();
  expect(stateOf('side')).toBe('peek');
  expect(set).not.toHaveBeenCalled();

  follow('widget_bars', { v: 1, side: { mode: 'pinned' } });
  expect(stateOf('side')).toBe('pinned');
  expect(track('side')).toBe('');
  leave(nav('side'));
  advance(5000);
  expect(stateOf('side')).toBe('pinned');
  expect(nav('side').querySelector('[data-bar-pin]')).not.toBeNull();
  nav('side').querySelector<HTMLElement>('[data-bar-edge]')!.click();
  await vi.advanceTimersByTimeAsync(0);
  expect(stateOf('side')).toBe('pinned');
  expect(set).not.toHaveBeenCalled();
});

test('show off hides the bar and closes its panel; one at a time folds the other bar and closes its panel', () => {
  keyIn('side', 'core.files').click();
  flushSync();
  follow('widget_bars', { ...AUTOHIDE_BARS, side: { mode: 'autohide', show: false } });
  expect(document.getElementById(RAIL_SPECS.side.id)).toBeNull();
  expect(railSlideout.shown('side')).toEqual([]);

  advance(RETRACT_MS);
  follow('widget_bars', { ...AUTOHIDE_BARS, together: 'one' });
  keyIn('side', 'core.files').click();
  flushSync();
  expect(barLead.edge).toBe('side');
  keyIn('bottom', 'core.task-manager').click();
  flushSync();
  expect(barLead.edge).toBe('bottom');
  expect(railSlideout.shown('side')).toEqual([]);
  expect(railSlideout.shown('bottom')).toEqual(['core.task-manager']);
  expect(stateOf('side')).toBe('folded');
  open('side');
  expect(stateOf('side')).toBe('peek');
  expect(railSlideout.shown('bottom')).toEqual(['core.task-manager']);
  expect(barLead.edge).toBe('bottom');
  railSlideout.close('bottom');
  flushSync();
  expect(barLead.edge).toBeNull();
});

test('a panel restored after a refresh never takes focus from the terminal; one a press opened does', () => {
  const terminal = document.createElement('textarea');
  document.body.appendChild(terminal);
  keyIn('side', 'core.files').click();
  flushSync();
  expect(railSlideout.lastOpenedByPress).toBeNull();
  expect(document.activeElement).toBe(document.querySelector('[data-rail-slideout="core.files"]'));
  unmountRails();
  terminal.focus();
  remountRails();
  flushSync();
  expect(document.querySelector('[data-rail-slideout="core.files"]')).not.toBeNull();
  expect(document.activeElement).toBe(terminal);
  terminal.remove();
});

test('one at a time on load with both bars pinned leads with the side bar and folds the bottom', () => {
  follow('widget_bars', { v: 1, together: 'one', side: { mode: 'pinned' }, bottom: { mode: 'pinned' } });
  flushSync();
  expect(barLead.edge).toBe('side');
  expect(stateOf('side')).toBe('pinned');
  expect(stateOf('bottom')).toBe('folded');
});

test('switching to one at a time with both panels open closes the folded bar panel', () => {
  keyIn('side', 'core.files').click();
  flushSync();
  keyIn('bottom', 'core.task-manager').click();
  flushSync();
  expect(railSlideout.shown('side')).toEqual(['core.files']);
  expect(railSlideout.shown('bottom')).toEqual(['core.task-manager']);
  follow('widget_bars', { ...AUTOHIDE_BARS, together: 'one' });
  flushSync();
  expect(stateOf('bottom')).toBe('held');
  expect(stateOf('side')).toBe('folded');
  expect(railSlideout.shown('side')).toEqual([]);
});

test('the handles draw the same DOM before and after the zone handle (golden, wrapper bar-handle rows)', () => {
  matchGolden('handle.bar.side', nav('side').querySelector('.rail__handle'));
  matchGolden('handle.bar.bottom', nav('bottom').querySelector('.rail__handle'));
  open('side');
  matchGolden('handle.bar.side.out', nav('side').querySelector('.rail__handle'));
});
