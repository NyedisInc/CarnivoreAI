/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';

vi.mock('../../../lib/terminal-search/cell-search', () => ({
  registerCellSearch: () => () => {}, toggleCellSearch: () => false, cellSearchOpen: () => null,
}));
vi.mock('../../../lib/terminal-search/mount-search', () => ({
  toggleTerminalSearch: () => {}, terminalSearchIsOpen: () => false,
}));

import { registerTerminalActions, registerTerminalOverlay, type TerminalOverlayContext } from './actions';
import type { ControllerLike } from '../../../lib/terminal-search/search-host';

const controller = {} as ControllerLike;

test('a factory covers cells registered before and after it, and stops with them', () => {
  const stopFirst = vi.fn();
  const factory = vi.fn((_context: TerminalOverlayContext) => stopFirst);
  const box = document.createElement('div');
  const before = registerTerminalActions('terminal:a', controller, document.createElement('div'), false, box);
  const remove = registerTerminalOverlay(factory);
  expect(factory).toHaveBeenCalledTimes(1);
  expect(factory.mock.calls[0]?.[0]).toMatchObject({ slot: 'terminal:a', host: box });
  const after = registerTerminalActions('terminal:b', controller, document.createElement('div'));
  expect(factory).toHaveBeenCalledTimes(2);
  before();
  expect(stopFirst).toHaveBeenCalledTimes(1);
  remove();
  expect(stopFirst).toHaveBeenCalledTimes(2);
  after();
});

test('registering the same overlay again starts nothing twice', () => {
  const factory = vi.fn(() => () => {});
  const remove = registerTerminalOverlay(factory);
  const off = registerTerminalActions('terminal:c', controller, document.createElement('div'));
  registerTerminalOverlay(factory);
  expect(factory).toHaveBeenCalledTimes(1);
  off();
  remove();
});
