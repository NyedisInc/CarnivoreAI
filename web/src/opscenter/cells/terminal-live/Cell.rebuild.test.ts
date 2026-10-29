/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { inputFocus } from '../../lib/input-focus.svelte';

interface FakeRow {
  session: { id: string };
  tmux_session: string | null;
  label: string | null;
  pinned_theme: string | null;
  activity_status: string;
  startup_gate: string | null;
  unread: boolean;
}

const listing = new SvelteMap<string, unknown>([
  ['status', 'ok'],
  ['rows', [] as FakeRow[]],
]);

const built: string[] = [];
const builtPanes: (string | null)[] = [];
let disposed = 0;

vi.mock('./client', () => ({
  startLiveTerminal: (_host: HTMLElement, _slot: string, session: unknown) => {
    const row = session as FakeRow;
    built.push(row?.session?.id ?? '');
    builtPanes.push(row?.tmux_session ?? null);
    return { client: { fake: true }, dispose(): void { disposed += 1; } };
  },
}));
vi.mock('./actions', () => ({ registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('./theme', () => ({ bindTerminalTheme: () => () => {} }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      get data() { return listing.get('rows'); },
      get status() { return listing.get('status'); },
      refresh: vi.fn(),
      fetchedAt: 1,
      error: null,
      stop() {},
    },
  };
});

const pointedAt: string[] = [];

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  built.length = 0;
  builtPanes.length = 0;
  pointedAt.length = 0;
  disposed = 0;
  inputFocus.release(inputFocus.owner ?? '');
  delete (globalThis as { TerminalBackground?: unknown }).TerminalBackground;
  listing.set('status', 'ok');
  listing.set('rows', []);
  vi.clearAllMocks();
});

function row(id: string, pane: string): FakeRow {
  return {
    session: { id },
    tmux_session: pane,
    label: 'a session',
    pinned_theme: null,
    activity_status: 'idle',
    startup_gate: null,
    unread: false,
  };
}

function poll(rows: FakeRow[], status = 'ok'): void {
  listing.set('status', status);
  listing.set('rows', rows);
  flushSync();
}

function render(instance: string): void {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, {
    target,
    props: { width: 900, height: 400, meta: metaFor(instance as SlotId), instance },
  }));
  flushSync();
}

test('a poll that changes nothing does not rebuild the terminal', () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  expect(built).toEqual(['ses_a']);

  poll([row('ses_a', 'carnivore_a')]);
  poll([row('ses_a', 'carnivore_a')]);
  poll([row('ses_a', 'carnivore_a')]);

  expect(built).toEqual(['ses_a']);
  expect(disposed).toBe(0);
});

test('a poll that changes only a status still does not rebuild the terminal', () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  expect(built).toEqual(['ses_a']);

  const working = row('ses_a', 'carnivore_a');
  working.activity_status = 'working';
  working.unread = true;
  poll([working]);

  expect(built).toEqual(['ses_a']);
  expect(disposed).toBe(0);
});

test('a row that arrives after the cell does builds the terminal then', () => {
  poll([], 'loading');
  render('terminal:ses_late');
  expect(built).toEqual([]);

  poll([row('ses_late', 'carnivore_late')]);

  expect(built).toEqual(['ses_late']);
  expect(disposed).toBe(0);
});

test('a session re-keyed onto a different pane rebuilds against the new one', () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  expect(builtPanes).toEqual(['carnivore_a']);

  poll([row('ses_a', 'carnivore_a_2')]);

  expect(builtPanes).toEqual(['carnivore_a', 'carnivore_a_2']);
  expect(disposed).toBe(1);
});

test('two cells on two sessions each build their own terminal, once', () => {
  poll([row('ses_a', 'carnivore_a'), row('ses_b', 'carnivore_b')]);
  render('terminal:ses_a');
  render('terminal:ses_b');
  expect(built).toEqual(['ses_a', 'ses_b']);

  poll([row('ses_a', 'carnivore_a'), row('ses_b', 'carnivore_b')]);

  expect(built).toEqual(['ses_a', 'ses_b']);
  expect(disposed).toBe(0);
});

test('a poll that changes nothing does not re-point the background painter', () => {
  (globalThis as { TerminalBackground?: unknown }).TerminalBackground = {
    setActiveSession(name: string): void { pointedAt.push(name); },
  };
  inputFocus.claim('terminal:ses_a');
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  expect(pointedAt).toEqual(['carnivore_a']);

  poll([row('ses_a', 'carnivore_a')]);
  poll([row('ses_a', 'carnivore_a')]);

  expect(pointedAt).toEqual(['carnivore_a']);
});

test('unmounting a cell still tears its terminal down', async () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  expect(built).toEqual(['ses_a']);

  for (const component of mounted.splice(0)) await unmount(component);

  expect(disposed).toBe(1);
});
