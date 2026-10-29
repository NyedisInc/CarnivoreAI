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

import { MENU_PAGES } from '../menu-page/menu-pages';
import { initMenuPageShell, resetMenuPageShell } from '../menu-page/menu-page-shell.svelte';
import { registerMainAreaLayer } from './main-area-layers';

let stopShell: () => void = () => {};
let screenUp = false;
let tabUp = true;
let stopLayers: Array<() => void> = [];
let menu: HTMLElement;
const settle = async (): Promise<void> => { await Promise.resolve(); await Promise.resolve(); };

beforeEach(() => {
  localStorage.clear();
  mountRails();
  barLead.edge = null;
  follow('widget_bars', null);
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.notes' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }] });
  resetMenuPageShell();
  for (const page of MENU_PAGES) {
    const div = document.createElement('div');
    div.id = page.containerId;
    document.body.append(div);
  }
  const ns: Record<string, unknown> = {};
  for (const page of MENU_PAGES) ns[page.closer] = () => document.getElementById(page.containerId)!.replaceChildren();
  stopShell = initMenuPageShell(document, { selectTab: vi.fn(), web: () => ns });
  screenUp = true;
  tabUp = true;
  stopLayers = [
    registerMainAreaLayer({ origin: 'sidebar', open: () => screenUp, close: () => { screenUp = false; } }),
    registerMainAreaLayer({ origin: 'tab', open: () => tabUp, close: () => { tabUp = false; } }),
  ];
  menu = document.createElement('div');
  menu.setAttribute('role', 'menu');
});
afterEach(() => {
  stopLayers.forEach((stop) => stop());
  stopShell();
  railSlideout.close();
  follow('widget_bars', null);
  unmountRails();
  document.body.innerHTML = '';
  document.body.className = '';
});

test('menu, menu page, sidebar-opened screen, unpinned panel close in that order; a tab layer never does', async () => {
  keyIn('side', 'core.files').click();
  flushSync();
  document.getElementById('settings-screen')!.append(document.createElement('div'));
  await settle();
  document.body.append(menu);
  expect(railSlideout.shown('side')).toEqual(['core.files']);

  escapeFrom(document.body);
  expect(document.getElementById('settings-screen')!.firstElementChild, 'the menu has the key; the page stays').not.toBeNull();
  menu.remove();

  escapeFrom(document.body);
  await vi.waitFor(() => expect(document.getElementById('settings-screen')!.firstElementChild).toBeNull());
  expect(screenUp, 'the page took the press; the sidebar screen stays').toBe(true);

  escapeFrom(document.body);
  expect(screenUp, 'the sidebar-opened screen closes').toBe(false);
  expect(railSlideout.shown('side'), 'the panel stays one more press').toEqual(['core.files']);

  escapeFrom(document.body);
  expect(railSlideout.shown('side'), 'the unpinned panel closes last').toEqual([]);
  expect(tabUp, 'a tab-strip item is never closed').toBe(true);
});

test('a pinned panel stays through every Escape', () => {
  follow('widget_bars', { v: 1, side: { mode: 'pinned' } });
  keyIn('side', 'core.files').click();
  flushSync();
  escapeFrom(document.body);
  expect(screenUp).toBe(false);
  escapeFrom(document.body);
  expect(railSlideout.shown('side')).toEqual(['core.files']);
});

test('Escape from a terminal closes nothing', () => {
  keyIn('side', 'core.files').click();
  flushSync();
  document.getElementById('docs-screen')!.append(document.createElement('div'));
  const screen = document.createElement('div');
  screen.className = 'xterm';
  const term = document.createElement('textarea');
  screen.append(term);
  document.body.append(screen);
  const event = escapeFrom(term);
  expect(event.defaultPrevented).toBe(false);
  expect(screenUp).toBe(true);
  expect(document.getElementById('docs-screen')!.firstElementChild).not.toBeNull();
  expect(railSlideout.shown('side')).toEqual(['core.files']);
});
