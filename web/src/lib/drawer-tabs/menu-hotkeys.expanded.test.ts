/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

const run = vi.hoisted(() => ({ providers: vi.fn(), hosts: vi.fn() }));
vi.mock('../../opscenter/shell/rail-items', () => ({ RAIL_RUN: run }));

import { listenExpandedMenuHotkeys } from './menu-hotkeys';
import { RAIL_HINT_ROWS } from '../../opscenter/shell/rail-hints';

let stop: () => void = () => {};
afterEach(() => {
  stop();
  document.body.replaceChildren();
  run.providers.mockClear();
  run.hosts.mockClear();
});

function key(target: Element, init: KeyboardEventInit): [boolean, boolean] {
  let reached = false;
  const spy = (): void => { reached = true; };
  target.addEventListener('keydown', spy);
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  target.removeEventListener('keydown', spy);
  return [event.defaultPrevented, reached];
}

function terminalInput(): HTMLTextAreaElement {
  const host = document.createElement('div');
  host.className = 'xterm';
  const ta = document.createElement('textarea');
  host.append(ta);
  document.body.append(host);
  return ta;
}

test('providers carries the letter a in the one hint table', () => {
  expect(RAIL_HINT_ROWS.find((r) => r.id === 'providers')?.keys).toBe('a');
});

test('a plain menu key typed in the terminal opens its page and never reaches the terminal', () => {
  stop = listenExpandedMenuHotkeys(window);
  const [prevented, reached] = key(terminalInput(), { key: 'a' });
  expect(run.providers).toHaveBeenCalledTimes(1);
  expect(prevented).toBe(true);
  expect(reached).toBe(false);
});

test('any other key, a modified key and a letter in a field outside the terminal pass through', () => {
  stop = listenExpandedMenuHotkeys(window);
  const term = terminalInput();
  expect(key(term, { key: 'x' })).toEqual([false, true]);
  expect(key(term, { key: 'a', ctrlKey: true })).toEqual([false, true]);
  const field = document.createElement('input');
  document.body.append(field);
  expect(key(field, { key: 'a' })).toEqual([false, true]);
  expect(run.providers).not.toHaveBeenCalled();
});

test('once stopped the listener is gone', () => {
  stop = listenExpandedMenuHotkeys(window);
  stop();
  key(terminalInput(), { key: 'a' });
  expect(run.providers).not.toHaveBeenCalled();
});
