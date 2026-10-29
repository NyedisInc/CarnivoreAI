/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { sessions } from '../../api';

vi.mock('./client', () => ({ startLiveTerminal: () => null }));
vi.mock('./actions', () => ({ registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('./theme', () => ({ bindTerminalTheme: () => () => {} }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      get data() { return rows; },
      get status() { return listingStatus; },
      refresh: vi.fn(),
      fetchedAt: 1,
      error: null,
      stop() {},
    },
  };
});

let rows: unknown[] | null = [];
let listingStatus = 'ok';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  vi.clearAllMocks();
});

function render(instance: string): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, {
    target,
    props: {
      width: 900,
      height: 40,
      meta: metaFor(instance as SlotId),
      instance,
    },
  }));
  flushSync();
  return target;
}

test('a cell showing a session the listing does not carry asks for the listing', () => {
  rows = [];
  render('terminal:ses_new');
  expect(sessions.refresh).toHaveBeenCalledWith(true);
});

test('a cell whose session IS in the listing asks for nothing', () => {
  rows = [{ session: { id: 'ses_known' }, tmux_session: 'carnivore_known', pinned_theme: null }];
  render('terminal:ses_known');
  expect(sessions.refresh).not.toHaveBeenCalled();
});

test('a session that never arrives is asked for ONCE, not once per update', () => {
  rows = [];
  render('terminal:ses_ghost');
  expect(sessions.refresh).toHaveBeenCalledTimes(1);
  rows = [{ session: { id: 'ses_other' }, tmux_session: 'carnivore_other', pinned_theme: null }];
  flushSync();
  expect(sessions.refresh).toHaveBeenCalledTimes(1);
});

test('the primary slot names no session, so it asks for nothing', () => {
  rows = [];
  render('terminal:@primary');
  expect(sessions.refresh).not.toHaveBeenCalled();
});
