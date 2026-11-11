/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { inputFocus } from '../../lib/input-focus.svelte';

/** One fake listing row: only the fields this cell reads. */
interface FakeRow {
  session: { id: string };
  tmux_session: string | null;
  label: string | null;
  pinned_theme: string | null;
  activity_status: string;
  startup_gate: string | null;
  unread: boolean;
}

/**
 * The one reactive holder both fake getters read, shaped like the real
 * resource's own `held` record: a status and the rows it answered with.
 */
const listing = new SvelteMap<string, unknown>([
  ['status', 'ok'],
  ['rows', [] as FakeRow[]],
]);

/** The session id handed to each `startLiveTerminal` call, in order. */
const built: string[] = [];
/** The tmux name handed to each `startLiveTerminal` call, in order. */
const builtPanes: (string | null)[] = [];
/** How many terminals were torn down. */
let disposed = 0;

// The cell's heavy collaborators. None of them is what this file measures, and
// each one builds or holds something real: an xterm on a div, a socket, a
// palette written onto a frame. The client stands in for all of it and counts.
vi.mock('./client', () => ({
  startLiveTerminal: (_host: HTMLElement, _slot: string, session: unknown) => {
    const row = session as FakeRow;
    built.push(row?.session?.id ?? '');
    builtPanes.push(row?.tmux_session ?? null);
    const ta = document.createElement('textarea'); ta.className = 'xterm-helper-textarea'; _host.appendChild(ta);
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

/** Every tmux name the background painter was pointed at, in order. */
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

/**
 * One listing row, freshly built.
 *
 * Description: EVERY CALL RETURNS A NEW OBJECT, which is the whole subject of
 *   this file. `poll.svelte.ts` parses `/sessions/list` and assigns the result
 *   over `held.data`, so identical fields arrive in a different object every
 *   five seconds; a fixture that handed back one cached object would be
 *   testing a listing this app does not have.
 * Inputs: id - the session id; pane - its tmux name.
 * Output: the row, in the wrapper shape `/sessions/list` answers with.
 * Example: row('ses_a', 'carnivore_a').session.id === 'ses_a'
 */
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

/**
 * Hand the cell one listing answer, the way the poll does.
 *
 * Description: ONE ATOMIC HAND-OVER, because the real resource assigns the
 *   whole array at once. Writing the rows one at a time with a flush between
 *   them would show the cell a moment with no row at all and tear the terminal
 *   down for a reason no poll ever produces.
 * Inputs: rows - the rows the listing carries; status - how the read went.
 * Output: nothing; effects are flushed before returning.
 * Example: poll([row('ses_a', 'carnivore_a')])
 */
function poll(rows: FakeRow[], status = 'ok'): void {
  listing.set('status', status);
  listing.set('rows', rows);
  flushSync();
}

/**
 * Mount one live terminal cell, in a box tall enough for a pane.
 *
 * Description: the height clears `TERMINAL_META`'s `pane` step (120px) and the
 *   width clears its `wide` step, so the cell renders its host element and the
 *   build effect has something to open a terminal into. Below the pane step the
 *   cell prints a line instead and nothing is ever built, which would make
 *   every count here a zero.
 * Inputs: instance - the slot id, whose tail is the session id.
 * Output: nothing; the mount is registered for teardown.
 * Example: render('terminal:ses_a')
 */
function render(instance: string): void {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, {
    target,
    props: { width: 900, height: 400, meta: metaFor(instance as SlotId), instance },
  }));
  flushSync();
}


test('B1: war room modal closing (same slot, second instance) must not null the tab claim', async () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  render('terminal:ses_a');
  inputFocus.claim('terminal:ses_a'); flushSync();
  const modal = mounted.pop()!;
  await unmount(modal);
  expect(inputFocus.owner).toBe('terminal:ses_a');
});

test('A1: a rebuild of the focused cell (pane re-keyed) must not drop the claim while its textarea keeps focus', () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  inputFocus.claim('terminal:ses_a'); flushSync();
  poll([row('ses_a', 'carnivore_a_2')]);
  expect(disposed).toBe(1);
  expect(inputFocus.owner).toBe('terminal:ses_a');
});

test('B2: moved tab - new instance claims, then old instance teardown runs', async () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  const old = mounted.pop()!;
  render('terminal:ses_a');
  inputFocus.claim('terminal:ses_a'); flushSync();
  await unmount(old);
  expect(inputFocus.owner).toBe('terminal:ses_a');
});

test('SANITY: sole instance unmount does null the claim (proves the test can go red)', async () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  const log: string[] = [];
  const ocl = inputFocus.claim.bind(inputFocus), orel = inputFocus.release.bind(inputFocus), ofg = inputFocus.forget.bind(inputFocus);
  vi.spyOn(inputFocus, 'claim').mockImplementation((id) => { ocl(id); log.push('claim->' + inputFocus.owner); });
  vi.spyOn(inputFocus, 'release').mockImplementation((id) => { orel(id); log.push('release->' + inputFocus.owner); });
  vi.spyOn(inputFocus, 'forget').mockImplementation((id) => { ofg(id); log.push('forget->' + inputFocus.owner); });
  inputFocus.claim('terminal:ses_a'); flushSync();
  log.push('pre-unmount owner=' + inputFocus.owner);
  await unmount(mounted.pop()!);
  log.push('post owner=' + inputFocus.owner);
  console.log('DIAG ' + log.join(' ; '));
  expect(inputFocus.owner).toBe(null);
});

test('C1 (THE USER-VISIBLE DEAD END): owner cleared while the cell textarea keeps DOM focus; a keystroke must re-claim', async () => {
  // @ts-expect-error plain script, no types
  await import('../../../../../client/js/terminal-input-ownership.js');
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  const tabBody = document.querySelectorAll('.oc-tl-body')[0]!;
  const ta = tabBody.querySelector('textarea') as HTMLTextAreaElement;
  ta.focus(); flushSync();
  expect(inputFocus.owner).toBe('terminal:ses_a');
  render('terminal:ses_a');
  await unmount(mounted.pop()!);
  flushSync();
  expect(document.activeElement).toBe(ta);
  expect(inputFocus.owner).toBe('terminal:ses_a');
  const w = window as unknown as { TerminalInputOwnership: { surfacePermits(o: string): boolean } };
  expect(w.TerminalInputOwnership.surfacePermits('terminal:ses_a')).toBe(true);
});

test('C2: with owner null and the textarea focused, a keydown or pointerdown inside the cell must claim (the gesture)', async () => {
  poll([row('ses_a', 'carnivore_a')]);
  render('terminal:ses_a');
  const ta = document.querySelector('.oc-tl-body textarea') as HTMLTextAreaElement;
  ta.focus(); flushSync();
  inputFocus.forget('terminal:ses_a'); flushSync();
  expect(inputFocus.owner).toBe(null);
  ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
  flushSync();
  expect(inputFocus.owner).toBe('terminal:ses_a');
});
