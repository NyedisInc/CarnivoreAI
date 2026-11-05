import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createAutoReloader } from './auto-reload';

let risk = false;
let spent = '';
let wake: () => void = () => {};
const reload = vi.fn();

function make() {
  return createAutoReloader({
    reload,
    atRisk: () => risk,
    isHidden: () => false,
    readSpent: () => spent,
    writeSpent: (k) => ((spent = k), true),
    listen: (r) => ((wake = r), () => {}),
    settleMs: 2000,
    recheckMs: 2000,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  risk = false;
  spent = '';
  reload.mockClear();
});
afterEach(() => vi.useRealTimers());

test('reloads after the settle delay when nothing is at risk', () => {
  make().consider('2|b');
  vi.advanceTimersByTime(1999);
  expect(reload).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(reload).toHaveBeenCalledTimes(1);
});

test('holds on unsent text, reloads once it clears, never twice for one key', () => {
  const r = make();
  risk = true;
  r.consider('2|b');
  vi.advanceTimersByTime(10_000);
  expect(reload).not.toHaveBeenCalled();
  risk = false;
  wake();
  expect(reload).toHaveBeenCalledTimes(1);
  r.consider('2|b');
  vi.advanceTimersByTime(10_000);
  expect(reload).toHaveBeenCalledTimes(1);
});

test('a cancel (dismiss) stops a pending reload', () => {
  const r = make();
  r.consider('2|b');
  r.consider(null);
  vi.advanceTimersByTime(10_000);
  expect(reload).not.toHaveBeenCalled();
});
