/** @vitest-environment jsdom */
import { flushSync } from 'svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { claimOpenMenu } from '../../../lib/drawer-tabs/open-menu';
import { MENU_HOST_ID, closeItemMenu } from '../../../lib/item-menu/open.svelte';
import { ROW_MENU_PANEL_ID } from '../../../lib/item-menu/row-context';
import { rowMenuBridge } from '../../../lib/item-menu/row-bridge';
import { openRowMenu } from './row-menu';
import type { SessionInfo } from '../../api';

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

type Win = Record<string, unknown>;
const win = window as unknown as Win;

const applied: Array<{ el: Element; pin: string | null }> = [];
const released = vi.fn();

beforeEach(() => {
  win.Themes = { applyScopeTo: (el: Element, ctx: { pinnedTheme: string | null }) => { applied.push({ el, pin: ctx.pinnedTheme }); return released; } };
  win.CloudeWeb = { rowMenu: rowMenuBridge };
});

afterEach(() => {
  closeItemMenu();
  flushSync();
  document.body.replaceChildren();
  applied.length = 0;
  released.mockClear();
  for (const k of ['Themes', 'CloudeWeb']) delete win[k];
});

const row = (pin: string | null): SessionInfo =>
  ({ tmux_session: 'cloude_a', label: 'a', activity_status: 'idle', pinned_theme: pin, session: { id: 'ses_a' } }) as unknown as SessionInfo;

const host = (): HTMLElement => document.getElementById(MENU_HOST_ID)!;

test('a tab\'s menu wears that session\'s own theme, scoped to the menu', () => {
  const tab = document.body.appendChild(document.createElement('button'));
  expect(openRowMenu(row('alien'), 'u-a', tab, { point: { x: 40, y: 20 } })).toBe(true);
  flushSync();
  expect(document.getElementById(ROW_MENU_PANEL_ID)).not.toBeNull();
  expect(applied).toEqual([{ el: host(), pin: 'alien' }]);
  expect(host().contains(document.getElementById(ROW_MENU_PANEL_ID))).toBe(true);
});

test('a tab with no theme asks for the global one (a null pin), and the scope is handed back on close', () => {
  const tab = document.body.appendChild(document.createElement('button'));
  openRowMenu(row(null), null, tab, { point: { x: 40, y: 20 } });
  expect(applied.map((a) => a.pin)).toEqual([null]);
  closeItemMenu();
  expect(released).toHaveBeenCalledOnce();
});

test('a fold-out is drawn inside its host, beside it, inside the window, and Escape retracts it alone', () => {
  const menu = document.body.appendChild(document.createElement('div'));
  const item = menu.appendChild(document.createElement('button'));
  const box = (el: Element, r: Partial<DOMRect>): void => { el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...r }) as DOMRect; };
  box(menu, { left: 1250, right: 1430, top: 300, bottom: 500 });
  box(item, { left: 1250, right: 1430, top: 470, bottom: 494 });
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 200 });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 180 });
  try {
    const onClose = vi.fn();
    expect(openRowMenu(row(null), null, item, { host: menu, onClose })).toBe(true);
    flushSync();
    const panel = document.getElementById(ROW_MENU_PANEL_ID)!;
    expect(menu.contains(panel), 'drawn inside the host menu, so a press in it is not outside the host').toBe(true);
    const left = parseInt(panel.style.left, 10);
    expect(left + 200).toBeLessThanOrEqual(1250 + 8);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(parseInt(panel.style.top, 10) + 180).toBeLessThanOrEqual(window.innerHeight);
    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    flushSync();
    expect(document.getElementById(ROW_MENU_PANEL_ID)).toBeNull();
    expect(menu.isConnected).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();
    expect(document.activeElement, 'focus goes back to the item it folded out of').toBe(item);
  } finally {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).offsetWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).offsetHeight;
  }
});

test('a fold-out does not claim the app-wide open-menu handle (it would close its host); a plain menu does', () => {
  const hostClose = vi.fn();
  const release = claimOpenMenu(hostClose);
  const menu = document.body.appendChild(document.createElement('div'));
  const item = menu.appendChild(document.createElement('button'));
  openRowMenu(row(null), null, item, { host: menu });
  flushSync();
  expect(hostClose).not.toHaveBeenCalled();
  closeItemMenu();
  flushSync();
  openRowMenu(row(null), null, item, { point: { x: 5, y: 5 } });
  flushSync();
  expect(hostClose).toHaveBeenCalledOnce();
  release();
});

test('a fold-out applies NO theme scope of its own (it inherits its host menu\'s), though its row is pinned', () => {
  const menu = document.body.appendChild(document.createElement('div'));
  const item = menu.appendChild(document.createElement('button'));
  openRowMenu(row('alien'), null, item, { host: menu });
  expect(applied).toHaveLength(0);
});
