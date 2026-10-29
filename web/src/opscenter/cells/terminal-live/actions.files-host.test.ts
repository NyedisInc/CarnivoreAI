/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { registerTerminalActions, terminalAction } from './actions';
import type { ControllerLike } from '../../../lib/terminal-search/search-host';

vi.mock('../../../lib/terminal-search/cell-search', () => ({
  registerCellSearch: () => () => {},
  openCellSearch: () => true,
}));

import { skillsDrawerOpen, setSkillsDrawer } from '../../../lib/session-skills/drawer.svelte';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('files and plugins carry the cell container to the loader, and skills toggles the cell skills drawer', () => {
  const openWhenReady = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady });
  const controller = { sessionActive: true, _sessionId: () => 'ses_two' } as unknown as ControllerLike;
  const container = document.createElement('div');
  const anchor = document.createElement('button');
  const stop = registerTerminalActions('terminal:two', controller, container);

  terminalAction('terminal:two', 'files', anchor);
  expect(openWhenReady).toHaveBeenLastCalledWith(anchor, controller, null, container);
  terminalAction('terminal:two', 'plugins', anchor);
  expect(openWhenReady).toHaveBeenLastCalledWith(anchor, controller, 'plugins', container);
  terminalAction('terminal:two', 'skills', anchor);
  expect(skillsDrawerOpen('terminal:two')).toBe(true);
  setSkillsDrawer('terminal:two', false);
  expect(openWhenReady).toHaveBeenCalledTimes(2);
  stop();

  terminalAction('terminal:two', 'files', anchor);
  expect(openWhenReady).toHaveBeenCalledTimes(2);
});

test('a cell with an overlay box hands the loader that box, never the terminal client container', () => {
  const openWhenReady = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady });
  const controller = { sessionActive: true } as unknown as ControllerLike;
  const body = document.createElement('div');
  const pane = document.createElement('div');
  body.append(pane);
  const anchor = document.createElement('button');
  const stop = registerTerminalActions('terminal:three', controller, pane, false, body);
  terminalAction('terminal:three', 'files', anchor);
  expect(openWhenReady).toHaveBeenLastCalledWith(anchor, controller, null, body);
  stop();
});

test('a cell with no overlay box hands the loader nothing, so the editor opens full screen', () => {
  const openWhenReady = vi.fn();
  vi.stubGlobal('ConfigEditorLoader', { openWhenReady });
  const controller = { sessionActive: true } as unknown as ControllerLike;
  const pane = document.createElement('div');
  const anchor = document.createElement('button');
  const stop = registerTerminalActions('terminal:four', controller, pane, false, null);
  terminalAction('terminal:four', 'files', anchor);
  expect(openWhenReady).toHaveBeenLastCalledWith(anchor, controller, null, null);
  stop();
});
