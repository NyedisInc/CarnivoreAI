/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from './CellFrame.svelte';
import TerminalFrame from './fixtures/TerminalFrame.svelte';
import CellInFrame from './fixtures/CellInFrame.svelte';
import ClosedSessionsCell from '../cells/closed-sessions/Cell.svelte';
import ThemesCell from '../cells/themes/Cell.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout, terminalLayout, type LayoutStore } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const SINGLETON = 'running-sessions' as SlotId;

let app: object | null = null;

function slotsOf(store: LayoutStore): string[] {
  return store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
}

function frame(slot: SlotId, store: LayoutStore): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(slot, META),
      instance: slot,
      widthState: '',
      heightState: '',
      store,
      body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
    },
  });
  flushSync();
  return target;
}

function tickItem(root: HTMLElement): HTMLElement {
  root.querySelector<HTMLButtonElement>('.oc-frame-corner')!.click();
  flushSync();
  const found = document.querySelector<HTMLElement>('.acm-menu [data-node="show-header"]');
  if (!found) throw new Error('no show header item');
  return found;
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  homeLayout.resetAll();
  terminalLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('the close x', () => {
  test('draws the separator before itself and hides a singleton at once', () => {
    expect(slotsOf(homeLayout)).toContain(SINGLETON);
    const root = frame(SINGLETON, homeLayout);
    const head = root.querySelector<HTMLElement>('.oc-frame-title')!;
    const close = head.querySelector<HTMLButtonElement>('[data-head-close]')!;
    expect(close).not.toBeNull();
    expect(head.querySelectorAll('.oc-head-sep')).toHaveLength(1);
    expect(close.previousElementSibling?.classList.contains('oc-head-sep')).toBe(true);
    expect(head.lastElementChild).toBe(close);

    close.click();
    flushSync();
    expect(homeLayout.state.layout.hidden).toContain(SINGLETON);
    expect(slotsOf(homeLayout)).not.toContain(SINGLETON);
    expect(document.querySelector('.acm-menu')).toBeNull();
  });

  test('removes an instance at once (nothing exists to restore it to)', () => {
    const slot = 'browser:probe' as SlotId;
    expect(terminalLayout.add('browser', 'probe')).toBeNull();
    expect(slotsOf(terminalLayout)).toContain(slot);
    const root = frame(slot, terminalLayout);
    root.querySelector<HTMLButtonElement>('[data-head-close]')!.click();
    flushSync();
    expect(slotsOf(terminalLayout)).not.toContain(slot);
    expect(terminalLayout.state.layout.hidden).not.toContain(slot);
  });

  test('is absent on the terminal page own pane and on a terminal viewer', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(TerminalFrame, { target, props: {} });
    flushSync();
    expect(target.querySelector('[data-head-close]')).toBeNull();
    unmount(app, { outro: false });
    app = null;

    expect(terminalLayout.add('terminal', 'ses_head_probe')).toBeNull();
    const root = frame('terminal:ses_head_probe' as SlotId, terminalLayout);
    expect(root.querySelector('.oc-frame-title')).not.toBeNull();
    expect(root.querySelector('[data-head-close]')).toBeNull();
  });
});

describe('the show header tick', () => {
  test('is on by default, takes this copy header off, and the same menu turns it back on', () => {
    const root = frame(SINGLETON, homeLayout);
    const item = tickItem(root);
    expect(item.getAttribute('role')).toBe('menuitemcheckbox');
    expect(item.getAttribute('aria-checked')).toBe('true');

    item.click();
    flushSync();
    expect(homeLayout.state.layout.headerOff).toEqual([SINGLETON]);
    expect(root.querySelector('.oc-frame-title')).not.toBeNull();
    expect(root.querySelector('.oc-frame-title--bare')).not.toBeNull();
    expect(root.querySelector('.oc-frame-corner-headless')).toBeNull();
    expect(root.querySelector('.oc-frame-title .oc-frame-corner')).not.toBeNull();

    const back = tickItem(root);
    expect(back.getAttribute('aria-checked')).toBe('false');
    back.click();
    flushSync();
    expect(homeLayout.state.layout.headerOff).toBeUndefined();
    expect(root.querySelector('.oc-frame-title')).not.toBeNull();
    expect(root.querySelector('.oc-frame-title--bare')).toBeNull();
  });

  test('is per copy: another widget on the same page keeps its header', () => {
    homeLayout.setHeaderShown(SINGLETON, false);
    const other = slotsOf(homeLayout).find((id) => id !== SINGLETON && metaFor(id as SlotId, META).chrome === 'card') as SlotId;
    expect(homeLayout.isHeaderShown(SINGLETON)).toBe(false);
    expect(homeLayout.isHeaderShown(other)).toBe(true);
  });

  test('is not offered on a widget that draws its own head (a terminal viewer)', () => {
    expect(terminalLayout.add('terminal', 'ses_tick_probe')).toBeNull();
    const root = frame('terminal:ses_tick_probe' as SlotId, terminalLayout);
    root.querySelector<HTMLButtonElement>('.oc-frame-corner')!.click();
    flushSync();
    expect(document.querySelector('.acm-menu')).not.toBeNull();
    expect(document.querySelector('[data-node="show-header"]')).toBeNull();
  });
});

describe('a header ticked off keeps its controls in the menu', () => {
  function headlessMenu(slot: SlotId, cell: typeof ClosedSessionsCell): HTMLElement {
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(CellInFrame, { target, props: { slot, cell } });
    flushSync();
    homeLayout.setHeaderShown(slot, false);
    flushSync();
    expect(target.querySelector('.oc-frame-title--bare')).not.toBeNull();
    target.querySelector<HTMLButtonElement>('.oc-frame-title .oc-frame-corner')!.click();
    flushSync();
    const menu = document.querySelector<HTMLElement>('.acm-menu');
    if (!menu) throw new Error('no menu');
    return menu;
  }

  test('closed sessions still offers every sort ordering', () => {
    const menu = headlessMenu('closed-sessions' as SlotId, ClosedSessionsCell);
    expect(menu.querySelectorAll('[data-node^="sort:"]').length).toBeGreaterThan(1);
  });

  test('themes still offers its favorites filter, as a checkbox item', () => {
    const menu = headlessMenu('themes' as SlotId, ThemesCell as typeof ClosedSessionsCell);
    const item = menu.querySelector<HTMLElement>('[data-node="favorites"]');
    expect(item?.getAttribute('role')).toBe('menuitemcheckbox');
  });
});
