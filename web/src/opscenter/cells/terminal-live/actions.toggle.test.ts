/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const search = vi.hoisted(() => ({ open: new Map<string, boolean>(), pageOpen: false }));

vi.mock('../../../lib/terminal-search/cell-search', () => ({
  registerCellSearch: (slot: string) => { search.open.set(slot, false); return () => search.open.delete(slot); },
  toggleCellSearch: (slot: string) => {
    if (!search.open.has(slot)) return false;
    search.open.set(slot, !search.open.get(slot));
    return true;
  },
  cellSearchOpen: (slot: string) => (search.open.has(slot) ? search.open.get(slot)! : null),
}));
vi.mock('../../../lib/terminal-search/mount-search', () => ({
  toggleTerminalSearch: () => { search.pageOpen = !search.pageOpen; },
  terminalSearchIsOpen: () => search.pageOpen,
}));

import { registerTerminalActions, retargetFiles, terminalAction, toolShowing } from './actions';
import { filesDrawer, foldFileDrawer } from '../../../lib/right-drawer/files.svelte';
import { followActiveTerminal, followSlot } from '../../../lib/right-drawer/files-follow.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import { flushSync } from 'svelte';
import type { ControllerLike } from '../../../lib/terminal-search/search-host';

const controller = { sessionActive: true } as unknown as ControllerLike;
const anchor = document.createElement('button');
let stops: Array<() => void> = [];

beforeEach(() => {
  search.open.clear();
  search.pageOpen = false;
  foldFileDrawer({ open: false });
});

afterEach(() => {
  for (const stop of stops.splice(0)) stop();
  vi.unstubAllGlobals();
});

test('search: the second press on a cell hides the panel the first showed', () => {
  stops.push(registerTerminalActions('terminal:a', controller, document.createElement('div')));
  terminalAction('terminal:a', 'search', anchor);
  expect(toolShowing('terminal:a', 'search')).toBe(true);
  terminalAction('terminal:a', 'search', anchor);
  expect(toolShowing('terminal:a', 'search')).toBe(false);
});

test('search: the page terminal toggles the page panel', () => {
  stops.push(registerTerminalActions('terminal:@primary', controller, document.createElement('div'), true));
  terminalAction('terminal:@primary', 'search', anchor);
  expect(search.pageOpen).toBe(true);
  expect(toolShowing('terminal:@primary', 'search')).toBe(true);
  terminalAction('terminal:@primary', 'search', anchor);
  expect(search.pageOpen).toBe(false);
});

test('files: a press opens this cell\'s files, the next press closes the drawer', () => {
  const openWhenReady = vi.fn(() => foldFileDrawer({ open: true, directory: null }));
  const closeDrawer = vi.fn(() => foldFileDrawer({ open: false }));
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady, closeDrawer });
  const box = document.createElement('div');
  stops.push(registerTerminalActions('terminal:a', controller, box));
  terminalAction('terminal:a', 'files', anchor);
  expect(openWhenReady).toHaveBeenCalledOnce();
  expect(filesDrawer.slot).toBe('terminal:a');
  expect(toolShowing('terminal:a', 'files')).toBe(true);
  expect(toolShowing('terminal:a', 'skills')).toBe(false);

  terminalAction('terminal:a', 'files', anchor);
  expect(closeDrawer).toHaveBeenCalledOnce();
  expect(openWhenReady).toHaveBeenCalledOnce();
  expect(toolShowing('terminal:a', 'files')).toBe(false);
});

test('files: what the control saw at pointerdown wins over the state at the click', () => {
  const openWhenReady = vi.fn();
  const closeDrawer = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady, closeDrawer });
  stops.push(registerTerminalActions('terminal:b', controller, document.createElement('div')));
  foldFileDrawer({ open: true, directory: null });
  filesDrawer.slot = 'terminal:b';
  terminalAction('terminal:b', 'files', anchor, false);
  expect(closeDrawer).not.toHaveBeenCalled();
  expect(openWhenReady).toHaveBeenCalledOnce();
});

test('the open browser follows the selected cell, and stays put when closed', () => {
  const retarget = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady: vi.fn(), retarget });
  const boxA = document.createElement('div');
  const boxB = document.createElement('div');
  const other = { sessionActive: true, id: 'b' } as unknown as ControllerLike;
  stops.push(registerTerminalActions('terminal:a', controller, boxA));
  stops.push(registerTerminalActions('terminal:b', other, boxB));

  expect(followSlot('terminal:b')).toBe(false);
  expect(retarget).not.toHaveBeenCalled();

  foldFileDrawer({ open: true, directory: null });
  filesDrawer.slot = 'terminal:a';
  expect(followSlot('terminal:b')).toBe(true);
  expect(retarget).toHaveBeenLastCalledWith(other, boxB);
  expect(filesDrawer.slot).toBe('terminal:b');

  stops.push(registerTerminalActions('terminal:@primary', controller, boxA, true));
  expect(followSlot('terminal:gone')).toBe(true);
  expect(retarget).toHaveBeenLastCalledWith(controller, boxA);
});

test('retargeting a cell that has gone does nothing', () => {
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady: vi.fn(), retarget: vi.fn() });
  expect(retargetFiles('terminal:nobody')).toBe(false);
});

test('selecting a terminal cell retargets the open browser, with no focus moved', () => {
  const retarget = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady: vi.fn(), retarget });
  const boxC = document.createElement('div');
  const third = { sessionActive: true, id: 'c' } as unknown as ControllerLike;
  stops.push(registerTerminalActions('terminal:c', third, boxC));
  foldFileDrawer({ open: true, directory: null });
  const stop = followActiveTerminal();
  stops.push(stop);
  inputFocus.claim('terminal:c');
  flushSync();
  expect(retarget).toHaveBeenLastCalledWith(third, boxC);
  retarget.mockClear();
  inputFocus.release('terminal:c');
  flushSync();
  expect(retarget).not.toHaveBeenCalled();
  inputFocus.forget('terminal:c');
});
