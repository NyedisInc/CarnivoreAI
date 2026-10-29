/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { openBrowserItemMenu, openRowMenu } from './row-menu';
import { asleepRows } from '../running-sessions/asleep';
import type { SessionRecord } from '../../api/types';

type Win = Record<string, unknown>;
const win = window as unknown as Win;
const contexts: Array<Record<string, unknown>> = [];
const opened = vi.fn((ctx: Record<string, unknown>, _anchor: Element, _at: unknown, _opts?: Record<string, unknown>) => {
  contexts.push(ctx);
  return true;
});

beforeEach(() => {
  win.CloudeWeb = { rowMenu: { openRow: opened, isOpen: () => false, closeRow: () => {} } };
  win.SessionSidebarGroupActions = {};
});
afterEach(() => {
  contexts.length = 0;
  opened.mockClear();
  for (const k of ['CloudeWeb', 'SessionSidebarGroupActions']) delete win[k];
  document.body.replaceChildren();
});

test('an asleep row reaches the menu as asleep, keyed by its uuid, with no live session id', () => {
  const rec = { id: 9, session_uuid: 'uuid-9', tmux_name: 'cloude_z', title: 'zed', asleep: true, agent_family: 'claude' } as unknown as SessionRecord;
  const row = asleepRows([rec], new Set())[0]!;
  const a = document.body.appendChild(document.createElement('button'));
  expect(openRowMenu(row, row.session_uuid, a, { point: { x: 1, y: 2 } })).toBe(true);
  expect(contexts[0]).toMatchObject({ asleep: true, status: 'asleep', sessionId: null, sessionUuid: 'uuid-9', agentFamily: 'claude', renameable: true });
  expect(opened.mock.calls[0]![2]).toEqual({ x: 1, y: 2 });
});

test.each([
  ['page', { isPage: true, isFile: false }],
  ['file', { isPage: false, isFile: true }],
  ['browser', { isPage: false, isFile: false }],
] as const)('a %s item reaches the menu as a browser-kind row, themed globally', (kind, flags) => {
  const a = document.body.appendChild(document.createElement('button'));
  expect(openBrowserItemMenu(kind, '0123456789abcdef', 'title', a, {})).toBe(true);
  expect(contexts[0]).toMatchObject({ kind: 'browser', name: 'browser:0123456789abcdef', label: 'title', ...flags });
  expect(opened.mock.calls[0]![3]).toMatchObject({ pinnedTheme: null });
});
