/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import {
  PARK_MS, PARKED_LAYOUTS, PARKED_TERMINALS, park, parkKey, parkedCount, releaseAll, setParking, shouldPark, unpark,
} from './parking';
import type { LiveTerminal } from './client';

const votes: Array<[unknown, boolean]> = [];

function handle(): LiveTerminal & { disposed: boolean } {
  const made = {
    client: {},
    disposed: false,
    dispose(): void {
      made.disposed = true;
    },
  };
  return made as unknown as LiveTerminal & { disposed: boolean };
}

beforeEach(() => {
  vi.useFakeTimers();
  votes.length = 0;
  (globalThis as Record<string, unknown>).TerminalSizeVote = {
    setTabHidden: (client: unknown, hidden: boolean) => votes.push([client, hidden]),
  };
  setParking(true);
});

afterEach(() => {
  setParking(false);
  vi.useRealTimers();
  delete (globalThis as Record<string, unknown>).TerminalSizeVote;
});

test('only a saved Layout left while the grid is up parks', () => {
  expect(shouldPark('layout:L1', 'layout:L2')).toBe(true);
  expect(shouldPark('layout:L1', 'cloude_api')).toBe(true);
  expect(shouldPark('layout:L1', 'layout:L1')).toBe(false);
  expect(shouldPark('layout:@pending', 'cloude_api')).toBe(false);
  expect(shouldPark('cloude_api', 'layout:L1')).toBe(false);
  setParking(false);
  expect(shouldPark('layout:L1', 'layout:L2')).toBe(false);
});

test('a parked terminal is withdrawn from the size vote and comes back to its own slot and session', () => {
  const host = document.createElement('div');
  const live = handle();
  park('layout:L1', parkKey('terminal:row:2', 'ses_2\ncloude_b'), host, live);
  expect(votes).toEqual([[live.client, true]]);
  expect(host.closest('[data-parked-terminals]')).not.toBeNull();
  expect(unpark('layout:L1', parkKey('terminal:row:2', 'ses_9\ncloude_b'))).toBeNull();
  expect(unpark('layout:L2', parkKey('terminal:row:2', 'ses_2\ncloude_b'))).toBeNull();
  const back = unpark('layout:L1', parkKey('terminal:row:2', 'ses_2\ncloude_b'));
  expect(back?.host).toBe(host);
  expect(back?.handle).toBe(live);
  expect(live.disposed).toBe(false);
  expect(parkedCount()).toBe(0);
});

test('the shelf keeps the last Layouts only, and at most its terminal cap', () => {
  const made: Array<ReturnType<typeof handle>> = [];
  for (let layout = 0; layout < PARKED_LAYOUTS + 1; layout += 1) {
    const live = handle();
    made.push(live);
    park(`layout:L${layout}`, parkKey('terminal:row:1', `s${layout}`), document.createElement('div'), live);
  }
  expect(made[0]!.disposed).toBe(true);
  expect(parkedCount()).toBe(PARKED_LAYOUTS);
  releaseAll();
  for (let i = 0; i < PARKED_TERMINALS + 2; i += 1) {
    park('layout:big', parkKey(`terminal:row:${i}`, `s${i}`), document.createElement('div'), handle());
  }
  expect(parkedCount()).toBe(PARKED_TERMINALS);
});

test('a parked terminal is ended after its time, and every one when the grid goes', () => {
  const late = handle();
  park('layout:L1', parkKey('terminal:row:1', 's1'), document.createElement('div'), late);
  vi.advanceTimersByTime(PARK_MS);
  expect(late.disposed).toBe(true);
  const kept = handle();
  park('layout:L1', parkKey('terminal:row:2', 's2'), document.createElement('div'), kept);
  setParking(false);
  expect(kept.disposed).toBe(true);
  expect(parkedCount()).toBe(0);
});
