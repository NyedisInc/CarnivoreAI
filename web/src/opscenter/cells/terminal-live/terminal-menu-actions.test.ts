import { expect, test } from 'vitest';
import { tabMenuActions, terminalMenuActions, widgetMenuActions } from './terminal-menu-actions';

const input = {
  runItem: () => {},
  ready: () => true,
  zoom: null,
  sizeMaster: null,
  sleepLabel: 'sleep',
  notReady: 'not ready',
};

test('the widget menu mirrors the strip: files and notes are back, theme keeps its words', () => {
  const actions = terminalMenuActions(input);
  expect(actions.map((a) => a.id)).toEqual(['search', 'theme', 'sleep', 'skills', 'plugins', 'files', 'notes']);
  expect(actions.find((a) => a.id === 'theme')?.label).toBe('session theme');
});

test('a plain shell widget menu leaves out the agent-only drawers and keeps the rest', async () => {
  const { itemApplies } = await import('./toolbar');
  const ids = terminalMenuActions({ ...input, applies: (id: string) => itemApplies(id, 'shell') }).map((a) => a.id);
  expect(ids).not.toContain('skills');
  expect(ids).not.toContain('plugins');
  for (const id of ['search', 'theme', 'sleep', 'files', 'notes']) expect(ids).toContain(id);
});

test('the terminal tab menu keeps search terminal alone', () => {
  const zoom = { label: 'zoom', run: () => {} };
  const sizeMaster = { on: false, run: () => {} };
  expect(tabMenuActions({ ...input, zoom, sizeMaster }).map((a) => a.id)).toEqual(['search']);
});

test('the widget menu offers open in terminal app only when the page passes it, in the shows group (R1-14)', () => {
  const widget = {
    ...input, menu: ['theme'], background: null, keepAwake: null, bookmarks: null, rowActions: null,
    words: { background: 'b', keepAwake: 'k', bookmarks: 'm', actions: 'a', openInTerminal: 'open in terminal app' },
  };
  expect(widgetMenuActions({ ...widget, openInTerminal: null }).map((a) => a.id)).not.toContain('open-in-terminal');
  let ran = 0;
  const entry = widgetMenuActions({ ...widget, openInTerminal: () => { ran += 1; } }).find((a) => a.id === 'open-in-terminal');
  expect(entry?.label).toBe('open in terminal app');
  expect(entry?.group).toBe('shows');
  entry?.run();
  expect(ran).toBe(1);
});
