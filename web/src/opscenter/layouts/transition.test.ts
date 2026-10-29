/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const listing = vi.hoisted(() => ({
  data: [
    { session: { id: 's-a' }, session_row_id: 1, label: 'api', tmux_session: 'cloude_api' },
    { session: { id: 's-b' }, session_row_id: 2, label: 'web', tmux_session: 'cloude_web' },
  ] as unknown[],
  status: 'ok',
  refresh: async () => undefined,
}));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));

const modal = vi.hoisted(() => ({
  opened: [] as Record<string, unknown>[],
  answer: null as ((value: boolean | null) => void) | null,
}));
vi.mock('../../lib/modal', () => ({
  openModal: (_component: unknown, props: Record<string, unknown>) =>
    new Promise((resolve) => {
      modal.opened.push(props);
      modal.answer = resolve;
    }),
}));

const api = vi.hoisted(() => ({
  create: vi.fn(),
  remove: vi.fn(async () => ({ layout: null, deleted: true, survivor: null, created: false })),
}));
vi.mock('./api', async (actual) => ({
  ...(await actual<typeof import('./api')>()),
  createLayout: api.create,
  deleteLayout: api.remove,
  listLayouts: async () => ({ status: 'ok', layouts: [], detail: null }),
}));

import { terminalLayout } from '../engine/layout.svelte';
import { openTab, resetTabCache, setGroups, tabsFor } from '../engine/tab-groups.svelte';
import { addSession } from '../engine/components-actions';
import { PRIMARY_SLOT } from '../engine/model';
import { abortNaming, isNaming, setSavedHandler, splitThrough } from './transition.svelte';
import { PENDING_KEY } from './mode.svelte';

const win = globalThis as unknown as Record<string, unknown>;
const saved = vi.fn();

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

beforeEach(() => {
  win.TerminalController = { _sessionId: () => 's-a', _currentTmuxName: () => 'cloude_api' };
  terminalLayout.bindSession('cloude_api', 1);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:2'] } });
  modal.opened.length = 0;
  api.create.mockReset();
  saved.mockReset();
  setSavedHandler(saved);
});

afterEach(async () => {
  if (isNaming()) abortNaming();
  modal.answer?.(false);
  await settle();
  terminalLayout.bindSession('');
  resetTabCache();
  localStorage.clear();
  delete win.TerminalController;
});

test('adding a TAB never comes through the funnel: no modal, the agent keeps it', async () => {
  openTab(terminalLayout, PRIMARY_SLOT, 'terminal:row:3');
  await settle();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, 'terminal:row:2', 'terminal:row:3']);
  expect(modal.opened).toHaveLength(0);
  expect(terminalLayout.session).toBe('cloude_api:1');
});

test('a split on a single agent lands on the provisional view and asks for a name, prefilled A + B', async () => {
  const own = 'cloudecode.opscenter.tabs.v1:cloude_api:1';
  const stored = localStorage.getItem(own);
  expect(addSession(terminalLayout, 'terminal', 's-b')).toBeNull();
  expect(terminalLayout.session).toBe(PENDING_KEY);
  expect(terminalLayout.state.layout.rows.flatMap((r) => r.slots.map((s) => s.id))).toContain('terminal:row:2');
  await settle();
  expect(modal.opened).toHaveLength(1);
  expect(modal.opened[0]!['suggested']).toBe('api + web');
  expect(localStorage.getItem(own), "the agent's own tabs are not written").toBe(stored);
  expect(localStorage.getItem('cloudecode.opscenter.layout.terminal.session.cloude_api:1')).toBeNull();
});

test('cancel puts the agent view back exactly, its tabs untouched, and saves nothing', async () => {
  const before = JSON.stringify(terminalLayout.state.layout);
  addSession(terminalLayout, 'terminal', 's-b');
  await settle();
  modal.answer!(false);
  await settle();
  expect(terminalLayout.session).toBe('cloude_api:1');
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, 'terminal:row:2']);
  expect(api.create).not.toHaveBeenCalled();
  expect(saved).not.toHaveBeenCalled();
});

test('a save posts exactly what is on screen, row keyed, and hands the Layout over', async () => {
  const layout = { layout_uuid: 'L1', name: 'api + web', members: [], revision: 1, shape: {} };
  api.create.mockResolvedValue({ layout, deleted: false, survivor: null, created: true });
  addSession(terminalLayout, 'terminal', 's-b');
  await settle();
  const save = modal.opened[0]!['save'] as (name: string) => Promise<string>;
  expect(await save('api + web')).toBe('');
  const [name, shape] = api.create.mock.calls[0]!;
  expect(name).toBe('api + web');
  expect(shape.groups[PRIMARY_SLOT].tabs).toEqual(['terminal:row:1', 'terminal:row:2']);
  expect(shape.layout.rows.flatMap((r: { slots: { id: string }[] }) => r.slots.map((s) => s.id))).toContain('terminal:row:2');
  modal.answer!(true);
  await settle();
  expect(saved).toHaveBeenCalledWith(layout, 's-a', 1);
});

test('a refused name stays in the dialog with the sentence, and nothing is handed over', async () => {
  const { ApiError } = await import('../api/auth.svelte');
  api.create.mockRejectedValue(new ApiError('x', 409, null, { detail: { code: 'layout_name_taken', detail: 'taken' } }));
  addSession(terminalLayout, 'terminal', 's-b');
  await settle();
  const save = modal.opened[0]!['save'] as (name: string) => Promise<string>;
  expect(await save('api + web')).toBe('a layout with that name already exists');
  expect(saved).not.toHaveBeenCalled();
  expect(terminalLayout.session).toBe(PENDING_KEY);
});

test('navigating away while naming cancels, and a create already in flight is removed again', async () => {
  let land: ((value: unknown) => void) | null = null;
  api.create.mockReturnValue(new Promise((resolve) => (land = resolve)));
  addSession(terminalLayout, 'terminal', 's-b');
  await settle();
  const save = modal.opened[0]!['save'] as (name: string) => Promise<string>;
  let cancelled = false;
  (modal.opened[0]!['watchAbort'] as (cancel: () => void) => void)(() => {
    cancelled = true;
    modal.answer!(false);
  });
  void save('api + web');
  abortNaming();
  expect(cancelled).toBe(true);
  land!({ layout: { layout_uuid: 'L2' }, deleted: false, survivor: null, created: true });
  await settle();
  expect(api.remove).toHaveBeenCalledWith('L2');
  expect(saved).not.toHaveBeenCalled();
  expect(terminalLayout.session).toBe('cloude_api:1');
});

test('a refused add is not a split: the agent view comes straight back, no modal', async () => {
  const done = splitThrough(() => 'cap' as const, (r) => r === null as never, 'no-row' as never);
  expect(done).toBe('cap');
  await settle();
  expect(terminalLayout.session).toBe('cloude_api:1');
  expect(modal.opened).toHaveLength(0);
});

test('with no row for the page session there is no member to name: refused, not applied', () => {
  win.TerminalController = { _sessionId: () => 's-unknown' };
  const apply = vi.fn(() => null);
  expect(splitThrough(apply, () => true, 'no-row')).toBe('no-row');
  expect(apply).not.toHaveBeenCalled();
});

test("a page holding an app id the listing never reports still splits: the row joins on the tmux name", async () => {
  win.TerminalController = { _sessionId: () => 's-gone', _currentTmuxName: () => 'cloude_api' };
  expect(addSession(terminalLayout, 'terminal', 's-b')).toBeNull();
  expect(terminalLayout.session).toBe(PENDING_KEY);
  await settle();
  expect(modal.opened).toHaveLength(1);
});

test('inside a Layout a split is applied at once, with no modal', async () => {
  terminalLayout.bindKey('layout:L9', terminalLayout.snapshot());
  const apply = vi.fn(() => null);
  splitThrough(apply, () => true, 'no-row');
  await settle();
  expect(apply).toHaveBeenCalledTimes(1);
  expect(modal.opened).toHaveLength(0);
  expect(terminalLayout.session).toBe('layout:L9');
});

test('a PAGE tab split beside the agent opens the naming popup, and the saved shape carries the page', async () => {
  const { splitTabOut } = await import('../engine/tab-groups.svelte');
  const { fromServerShape } = await import('./shape');
  const page = 'page:0123456789abcdef';
  const layout = { layout_uuid: 'L2', name: 'api + page', members: [], revision: 1, shape: {} };
  api.create.mockResolvedValue({ layout, deleted: false, survivor: null, created: true });
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, page] } });
  const result = splitThrough(
    () => splitTabOut(terminalLayout, page, { kind: 'stack', of: PRIMARY_SLOT as never, edge: 'below' }),
    (done) => done === 'split',
    null,
  );
  expect(result).toBe('split');
  expect(terminalLayout.session).toBe(PENDING_KEY);
  await settle();
  expect(modal.opened).toHaveLength(1);
  const save = modal.opened[0]!['save'] as (name: string) => Promise<string>;
  expect(await save('api + page')).toBe('');
  const shape = api.create.mock.calls[0]![1];
  const pageSlot = 'terminal:pg-0123456789abcdef';
  expect(shape.groups[pageSlot].tabs).toEqual([page]);
  expect(shape.groups[PRIMARY_SLOT].tabs).toEqual(['terminal:row:1']);
  const back = fromServerShape(shape, 1)!;
  expect(back.groups[pageSlot]?.tabs).toEqual([page]);
  expect(back.layout!.rows.flatMap((r) => r.slots.map((s) => s.id as string))).toContain(pageSlot);
  modal.answer!(true);
  await settle();
  expect(saved).toHaveBeenCalled();
});
