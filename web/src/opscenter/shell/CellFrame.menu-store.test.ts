/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from './CellFrame.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout, terminalLayout, type LayoutStore } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const SESSION = 'ses_menu_probe';
const SLOT = `terminal:${SESSION}` as SlotId;

function slotsOf(store: LayoutStore): string[] {
  return store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
}

function openMenu(store: LayoutStore): { app: object; items: HTMLElement[] } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(SLOT, META),
      instance: SLOT,
      widthState: '',
      heightState: '',
      store,
      body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
    },
  });
  flushSync();
  const corner = target.querySelector('.oc-frame-corner') as HTMLButtonElement;
  expect(corner).not.toBe(null);
  corner.click();
  flushSync();
  const items = [...document.querySelectorAll<HTMLElement>('.acm-menu [role="menuitem"]')];
  return { app, items };
}

function item(items: HTMLElement[], action: string): HTMLElement {
  const found = items.find((one) => one.dataset['node'] === action);
  if (!found) throw new Error(`no ${action} item`);
  return found;
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  terminalLayout.add('terminal', SESSION);
  homeLayout.add('terminal', SESSION);
});

afterEach(() => {
  terminalLayout.resetAll();
  homeLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('a corner menu press acts on the store the frame was handed', () => {
  test('remove on the TERMINAL surface takes the terminal slot and leaves home alone', () => {
    expect(slotsOf(terminalLayout)).toContain(SLOT);
    const homeBefore = slotsOf(homeLayout);
    expect(homeBefore).toContain(SLOT);

    const { app, items } = openMenu(terminalLayout);
    expect(items[items.length - 1]?.dataset['node']).toBe('remove-widget');
    item(items, 'remove-widget').click();
    flushSync();

    expect(slotsOf(terminalLayout)).not.toContain(SLOT);
    expect(slotsOf(homeLayout)).toEqual(homeBefore);
    unmount(app, { outro: false });
  });

  test('remove on the HOME surface takes the home slot and leaves the terminal alone', () => {
    const terminalBefore = slotsOf(terminalLayout);
    expect(terminalBefore).toContain(SLOT);
    expect(slotsOf(homeLayout)).toContain(SLOT);

    const { app, items } = openMenu(homeLayout);
    item(items, 'remove-widget').click();
    flushSync();

    expect(slotsOf(homeLayout)).not.toContain(SLOT);
    expect(slotsOf(terminalLayout)).toEqual(terminalBefore);
    unmount(app, { outro: false });
  });
});
