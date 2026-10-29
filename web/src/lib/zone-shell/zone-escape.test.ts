/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ label: 'api', session_row_id: 7, session: { id: 'ses_1' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { ...(await importOriginal<Record<string, unknown>>()), entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD, RAIL_SPECS, type RailEdge } from '../session-rail/rail-model';
import { railSlideout } from '../session-rail/slideout.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from '../session-rail/rail-test-harness';
import { barLead } from '../widget-bars/bar-lead.svelte';

// jsdom has no popover API; the key menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

/** A real Escape keydown from a target; returns the event. */
function escapeFrom(target: Element): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  flushSync();
  return event;
}

const nav = (edge: RailEdge): HTMLElement => document.getElementById(RAIL_SPECS[edge].id)!;
const stateOf = (edge: RailEdge): string | undefined => nav(edge).dataset['barState'];
const handle = (edge: RailEdge): HTMLElement => nav(edge).querySelector<HTMLElement>('[data-bar-handle]')!;
const panel = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-edge="side"]')!;
/** A mouse click on the handle (detail 1: a click with no detail is the keyboard's): an unpinned bar comes out. */
const pressHandle = (edge: RailEdge): void => { handle(edge).dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 })); flushSync(); };
/** A terminal's input, as xterm draws it. */
function terminalInput(parent: Element): HTMLTextAreaElement {
  const screen = document.createElement('div');
  screen.className = 'xterm';
  const term = document.createElement('textarea');
  screen.append(term);
  parent.append(screen);
  return term;
}

beforeEach(() => {
  localStorage.clear();
  mountRails();
  barLead.edge = null;
  follow('widget_bars', null);
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.notes' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }] });
});
afterEach(() => {
  railSlideout.close();
  follow('widget_bars', null);
  unmountRails();
  document.body.innerHTML = '';
});

test('an unpinned open bar hides on Escape from the page body, its panel with it; a pinned one stays', () => {
  keyIn('side', 'core.files').click();
  flushSync();
  expect(railSlideout.shown('side')).toEqual(['core.files']);
  const event = escapeFrom(document.body);
  expect(railSlideout.shown('side'), 'the unpinned bar\'s panel goes').toEqual([]);
  expect(stateOf('side')).toBe('handle');
  expect(event.defaultPrevented, 'the Escape is claimed').toBe(true);

  pressHandle('side');
  expect(stateOf('side')).toBe('peek');
  const main = document.createElement('main');
  document.body.append(main);
  escapeFrom(main);
  expect(stateOf('side'), 'a peek folds in on an Escape from the main area').toBe('handle');

  follow('widget_bars', { v: 1, side: { mode: 'pinned' } });
  keyIn('side', 'core.files').click();
  flushSync();
  const kept = escapeFrom(document.body);
  expect(railSlideout.shown('side'), 'a pinned bar keeps its panel').toEqual(['core.files']);
  expect(stateOf('side')).not.toBe('handle');
  expect(kept.defaultPrevented, 'nothing to hide: the key is not claimed').toBe(false);
});

test('Escape inside a terminal leaves the bar, whether the terminal is in the main area or in the panel', () => {
  keyIn('side', 'core.files').click();
  flushSync();
  const outside = escapeFrom(terminalInput(document.body));
  expect(railSlideout.shown('side'), 'the terminal owns its Escape').toEqual(['core.files']);
  expect(outside.defaultPrevented).toBe(false);
  const body = panel().querySelector<HTMLElement>('[data-rail-body]') ?? panel();
  escapeFrom(terminalInput(body));
  expect(railSlideout.shown('side'), 'the program in the panel owns its Escape').toEqual(['core.files']);
  escapeFrom(body);
  expect(railSlideout.shown('side'), 'an Escape from inside an unpinned bar\'s panel closes it').toEqual([]);
});

test('a pinned bar\'s open panel keeps Escape from inside it; a menu open there closes alone', () => {
  follow('widget_bars', { v: 1, side: { mode: 'pinned' } });
  keyIn('side', 'core.files').click();
  flushSync();
  const body = panel().querySelector<HTMLElement>('[data-rail-body]') ?? panel();
  const plain = escapeFrom(body);
  expect(railSlideout.shown('side'), 'a pinned panel never closes on Escape').toEqual(['core.files']);
  expect(stateOf('side')).not.toBe('handle');
  expect(plain.defaultPrevented, 'nothing to close: the key is not claimed').toBe(false);

  keyIn('side', 'core.files').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  const menu = (): Element | null => document.querySelector('[role="menu"]');
  expect(menu(), 'the key menu is open').not.toBeNull();
  escapeFrom(body);
  expect(menu(), 'the menu closed').toBeNull();
  expect(railSlideout.shown('side'), 'the panel stays under the menu').toEqual(['core.files']);
  escapeFrom(body);
  expect(railSlideout.shown('side'), 'and stays after it').toEqual(['core.files']);
});

test('with both bars out and unpinned, one Escape hides one bar: the most recently opened first', () => {
  pressHandle('bottom');
  pressHandle('side');
  expect([stateOf('side'), stateOf('bottom')]).toEqual(['peek', 'peek']);
  escapeFrom(document.body);
  expect([stateOf('side'), stateOf('bottom')], 'the side bar opened last').toEqual(['handle', 'peek']);
  escapeFrom(document.body);
  expect(stateOf('bottom')).toBe('handle');

  pressHandle('side');
  pressHandle('bottom');
  escapeFrom(document.body);
  expect([stateOf('side'), stateOf('bottom')], 'now the bottom bar opened last').toEqual(['peek', 'handle']);
});

test('Escape with a menu open closes only the menu; the next one hides the bar', () => {
  pressHandle('side');
  keyIn('side', 'core.files').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  const menu = (): Element | null => document.querySelector('[role="menu"]');
  expect(menu(), 'the key menu is open').not.toBeNull();
  escapeFrom(document.body);
  expect(menu(), 'the menu closed').toBeNull();
  expect(stateOf('side'), 'the bar stays out').toBe('peek');
  escapeFrom(document.body);
  expect(stateOf('side')).toBe('handle');
});
