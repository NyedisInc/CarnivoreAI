/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('../../../lib/terminal-search/cell-search', () => ({
  registerCellSearch: () => () => {}, toggleCellSearch: () => false, cellSearchOpen: () => null,
}));
vi.mock('../../../lib/terminal-search/mount-search', () => ({
  toggleTerminalSearch: () => {}, terminalSearchIsOpen: () => false,
}));

import { registerTerminalActions } from './actions';
import type { ControllerLike } from '../../../lib/terminal-search/search-host';

afterEach(() => vi.useRealTimers());

test('registering and writing starts no card scanner, timer or listener', () => {
  vi.useFakeTimers();
  const listen = vi.spyOn(window, 'addEventListener');
  const onWriteParsed = vi.fn(() => ({ dispose() {} }));
  const controller = { sessionActive: true, term: { onWriteParsed, registerDecoration: vi.fn() } } as unknown as ControllerLike;
  const stop = registerTerminalActions('terminal:ses_x', controller, document.createElement('div'));
  expect(onWriteParsed).not.toHaveBeenCalled();
  expect(listen.mock.calls.some(([type]) => type === 'terminal-created')).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
  stop();
  listen.mockRestore();
});

test('the card host and its scanner no longer exist', () => {
  const dir = resolve(__dirname, '../../../lib/crosstalk');
  for (const gone of ['cards.ts', 'anchors.ts', 'collapsed-calls.ts', 'card-prefs.ts']) expect(existsSync(resolve(dir, gone))).toBe(false);
  expect(existsSync(resolve(dir, 'CrosstalkCard.svelte'))).toBe(true);
});
