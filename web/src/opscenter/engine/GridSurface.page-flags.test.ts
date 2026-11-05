/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import GridSurface from './GridSurface.svelte';
import CellFrame from '../shell/CellFrame.svelte';
import { createLayoutStore, homeLayout } from './layout.svelte';
import { META, metaFor } from './meta';
import type { SlotId } from './types';
import { inputFocus } from '../lib/input-focus.svelte';

const TERMINAL = 'terminal:ses_pf_grid' as SlotId;
const OUTSIDE = 'notes' as SlotId;
const apps: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  homeLayout.add('terminal', 'ses_pf_grid');
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  inputFocus.forget(TERMINAL);
  inputFocus.release(OUTSIDE);
  homeLayout.resetAll();
  document.body.className = '';
  document.body.replaceChildren();
  localStorage.clear();
});

function host(id: string, parent: HTMLElement = document.body): HTMLElement {
  const el = document.createElement('div');
  el.id = id;
  parent.append(el);
  return el;
}

function surface(target: HTMLElement): ReturnType<typeof mount> {
  const renderCell = createRawSnippet(() => ({ render: () => '<div></div>' }));
  const app = mount(GridSurface, { target, props: { store: createLayoutStore('terminal'), renderCell } as never });
  apps.push(app);
  flushSync();
  return app;
}

function frame(target: HTMLElement, slot: SlotId): void {
  apps.push(
    mount(CellFrame, {
      target,
      props: {
        meta: metaFor(slot, META),
        instance: slot,
        widthState: '',
        heightState: '',
        store: homeLayout,
        body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
      },
    }),
  );
  flushSync();
}

test('a surface that is a child of #terminal-grid raises ps-grid-surface on body and the grid, and clears on unmount', () => {
  const grid = host('terminal-grid');
  const app = surface(grid);
  expect(document.body.classList.contains('ps-grid-surface')).toBe(true);
  expect(grid.classList.contains('ps-grid-surface')).toBe(true);
  unmount(app);
  apps.splice(apps.indexOf(app), 1);
  expect(document.body.classList.contains('ps-grid-surface')).toBe(false);
  expect(grid.classList.contains('ps-grid-surface')).toBe(false);
});

test('a surface anywhere else (the home dashboard) raises nothing', () => {
  surface(host('launchpad-screen'));
  expect(document.body.classList.contains('ps-grid-surface')).toBe(false);
});

test('a frame holding input inside #terminal-grid raises ps-grid-focus, and releasing input clears it', () => {
  const grid = host('terminal-grid');
  frame(grid, TERMINAL);
  expect(grid.classList.contains('ps-grid-focus')).toBe(false);
  inputFocus.claim(TERMINAL);
  flushSync();
  expect(grid.classList.contains('ps-grid-focus')).toBe(true);
  inputFocus.release(TERMINAL);
  flushSync();
  expect(grid.classList.contains('ps-grid-focus')).toBe(false);
});

test('input owned by a cell outside #terminal-grid leaves ps-grid-focus off, so the terminal panes are not dimmed', () => {
  const grid = host('terminal-grid');
  surface(grid);
  frame(host('warroom-screen'), OUTSIDE);
  inputFocus.claim(OUTSIDE);
  flushSync();
  expect(inputFocus.owner).toBe(OUTSIDE);
  expect(grid.classList.contains('ps-grid-focus')).toBe(false);
});

test('unmounting the focused frame clears ps-grid-focus', () => {
  const grid = host('terminal-grid');
  frame(grid, TERMINAL);
  inputFocus.claim(TERMINAL);
  flushSync();
  expect(grid.classList.contains('ps-grid-focus')).toBe(true);
  unmount(apps.pop()!);
  expect(grid.classList.contains('ps-grid-focus')).toBe(false);
});
