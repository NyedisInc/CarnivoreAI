/* the home screen */
import { t } from '../../lib/i18n/index.svelte';
import { whenLegacyBootComplete } from '../../lib/legacy-boot';
import { authFetch } from '../api/auth.svelte';
import { subscribe } from '../api';
import { homeLayout } from './layout.svelte';
import { onHomeChange } from './arrangement-events';
import { gestureActive } from './pointer';
import { STORAGE_KEYS } from './persist';
import { cacheSeedLevel, homeSeedLevel, seedControl } from './home-seed';
import { preferencesApi, type PreferencesApi } from './arrangement-sync.svelte';
import {
  HOME_BOARD_ID,
  mergeBoards,
  parseBoards,
  pickActiveBoard,
  readActiveBoard,
  writeActiveBoard,
  type Board,
  type BoardSummary,
} from './home-boards';
import type { Layout } from './types';

export const HOME_LAYOUT_FIELD = 'home_layout';

export const WRITE_DELAY = 600;

const RETRY_DELAY = 300;

export interface HomeValue {
  v: 2;
  boards: Board[];
  analytics_seed: number;
  active?: string;
}

export function parseHome(value: unknown): HomeValue | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const held = value as Record<string, unknown>;
  const layout = held['layout'];
  const boards =
    parseBoards(held['boards']) ??
    (layout && typeof layout === 'object' && !Array.isArray(layout)
      ? [{ id: HOME_BOARD_ID, name: HOME_BOARD_ID, layout: layout as Layout }]
      : null);
  if (!boards) return null;
  const seed = held['analytics_seed'];
  const level = typeof seed === 'number' && Number.isInteger(seed) ? Math.min(2, Math.max(0, seed)) : 0;
  const active = held['active'];
  const out: HomeValue = { v: 2, boards, analytics_seed: level };
  if (typeof active === 'string' && boards.some((board) => board.id === active)) out.active = active;
  return out;
}

let synced: HomeValue | null = null;
let known = false;
let dirty = false;
let held: HomeValue | null = null;
let applying = false;
let inflight = false;
let started = false;
let popoutMode = false;
let boards: Board[] = [];
let activeId = HOME_BOARD_ID;
let shownId = HOME_BOARD_ID;
let viewingId: string | null = null;
let viewDirty = false;
let viewEdit = 0;
let viewTimer: ReturnType<typeof setTimeout> | undefined;
let activeChosen = false;
let wallboardId: string | null = null;
let popoutEdits = false;
let popoutEdit = 0;
let writeTimer: ReturnType<typeof setTimeout> | undefined;
let heldTimer: ReturnType<typeof setTimeout> | undefined;
let stops: Array<() => void> = [];

export const homeBoards: {
  list: BoardSummary[];
  active: string;
  viewing: string | null;
  layouts: Record<string, Layout>;
  ready: boolean;
} = $state({
  list: [{ id: HOME_BOARD_ID, name: HOME_BOARD_ID }],
  active: HOME_BOARD_ID,
  viewing: null,
  layouts: {},
  ready: false,
});

function publishBoards(): void {
  homeBoards.list = (boards.length ? boards : [{ id: HOME_BOARD_ID, name: HOME_BOARD_ID }]).map(({ id, name }) => ({ id, name }));
  homeBoards.layouts = Object.fromEntries(boards.map((board) => [board.id, board.layout]));
  homeBoards.active = activeId;
  homeBoards.viewing = viewingId;
  homeBoards.ready = known;
}

function liveLayout(): Layout {
  return $state.snapshot(homeLayout.state.layout) as Layout;
}

function current(): HomeValue {
  const live = liveLayout();
  const list: Board[] = boards.length ? boards : [{ id: HOME_BOARD_ID, name: HOME_BOARD_ID, layout: live }];
  return {
    v: 2,
    boards: list.map((board) => (board.id === activeId && !viewingId ? { ...board, layout: live } : board)),
    analytics_seed: homeSeedLevel(),
    active: activeId,
  };
}

function referencedAnalytics(): Set<string> {
  const ids = new Set<string>();
  for (const board of current().boards) {
    for (const row of board.layout.rows) for (const slot of row.slots) if (slot.id.startsWith('analytics:')) ids.add(slot.id);
    for (const id of board.layout.hidden ?? []) if (id.startsWith('analytics:')) ids.add(id);
  }
  return ids;
}

function remember(value: HomeValue): void {
  synced = value;
  seedControl.setServer(value.analytics_seed);
}

function wantsWrite(): boolean {
  return dirty || seedControl.pending() > (synced?.analytics_seed ?? 0);
}

function noteLocal(): void {
  if (applying) return;
  if (viewingId) {
    noteViewEdit();
    return;
  }
  dirty = true;
  scheduleWrite();
}

function scheduleWrite(delay = WRITE_DELAY): void {
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    writeTimer = undefined;
    void flush();
  }, delay);
}

export function applyHome(next: HomeValue): void {
  if (gestureActive()) {
    held = next;
    if (heldTimer === undefined) {
      heldTimer = setTimeout(() => {
        heldTimer = undefined;
        const value = held;
        held = null;
        if (value) applyHome(value);
      }, RETRY_DELAY);
    }
    return;
  }
  held = null;
  remember(next);
  known = true;
  cacheSeedLevel(next.analytics_seed);
  boards = next.boards;
  const wanted = popoutMode
    ? (wallboardId ?? next.active ?? readActiveBoard())
    : (next.active ?? (activeChosen ? activeId : readActiveBoard()));
  const picked = pickActiveBoard(boards, wanted);
  if (viewingId && (!boards.some((board) => board.id === viewingId) || viewingId === picked)) {
    const carried = viewDirty && viewingId === picked;
    viewingId = null;
    viewDirty = false;
    if (carried) {
      dirty = true;
      scheduleWrite();
    }
  }
  const shown = viewingId ?? picked;
  const moved = shown !== shownId;
  activeId = picked;
  shownId = shown;
  activeChosen = true;
  if (!popoutMode) writeActiveBoard(picked);
  publishBoards();
  if ((viewingId ? viewDirty : dirty) && !moved) return;
  if (moved) {
    dirty = false;
    viewDirty = false;
  }
  const layout = boards.find((board) => board.id === shownId)!.layout;
  if (JSON.stringify(liveLayout()) === JSON.stringify(layout)) return;
  let migrated = false;
  applying = true;
  try {
    migrated = homeLayout.adopt(layout);
  } finally {
    applying = false;
  }
  if (migrated && !popoutMode) noteLocal();
}

async function flush(): Promise<void> {
  const api = preferencesApi();
  if (!wantsWrite() || !api || popoutMode) return;
  if (inflight || gestureActive() || api.status() !== api.HYDRATED || !known) {
    scheduleWrite(RETRY_DELAY * 4);
    return;
  }
  const next = current();
  dirty = false;
  inflight = true;
  try {
    const result = await api.set(HOME_LAYOUT_FIELD, next);
    if (result.status === 'stale_revision') {
      await resolveConflict(api, next);
    } else if (result.status === 'committed' || result.status === 'unchanged') {
      remember(next);
    } else if (result.status === 'refused') {
      dirty = true;
      scheduleWrite(RETRY_DELAY * 4);
    }
  } catch (error) {
    console.warn('[home layout] write failed', error);
    dirty = true;
    scheduleWrite(RETRY_DELAY * 4);
  } finally {
    inflight = false;
  }
  if (wantsWrite()) scheduleWrite();
}

async function resolveConflict(api: PreferencesApi, ours: HomeValue): Promise<void> {
  const theirs = parseHome(api.committedValue(HOME_LAYOUT_FIELD));
  if (theirs) remember(theirs);
  const merged: HomeValue = {
    ...ours,
    boards: theirs ? mergeBoards(ours.boards, theirs.boards, activeId) : ours.boards,
    analytics_seed: Math.max(ours.analytics_seed, theirs?.analytics_seed ?? 0),
    active: theirs?.active ?? ours.active };
  const again = await api.set(HOME_LAYOUT_FIELD, merged);
  if (again.status === 'committed' || again.status === 'unchanged') {
    remember(merged);
    boards = merged.boards;
    publishBoards();
    homeLayout.announce(t('opscenter.tabs.sync_merged'));
    return;
  }
  if (again.status === 'stale_revision') {
    const latest = parseHome(api.committedValue(HOME_LAYOUT_FIELD));
    if (latest) applyHome(latest);
    homeLayout.announce(t('opscenter.tabs.sync_lost'));
    return;
  }
  dirty = true;
}

export async function flushHome(): Promise<void> {
  if (popoutMode || !dirty) return;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  writeTimer = undefined;
  await flush();
}

function notePopoutEdit(): void {
  if (applying) return;
  dirty = true;
  popoutEdit += 1;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    writeTimer = undefined;
    void savePopoutBoard();
  }, WRITE_DELAY);
}

async function savePopoutBoard(): Promise<void> {
  const carried = popoutEdit;
  const saved = await putBoard(wallboardId);
  if (!saved || carried === popoutEdit) dirty = false;
}

async function putBoard(id: string | null): Promise<boolean> {
  if (!id || !boards.some((board) => board.id === id)) {
    homeLayout.announce(t('dashboards.save_failed'));
    return false;
  }
  try {
    await authFetch(`/dashboards/${encodeURIComponent(id)}/layout`, {
      method: 'PUT',
      body: JSON.stringify({ layout: liveLayout() }),
    });
    return true;
  } catch (error) {
    console.warn('[home layout] dashboard save failed', error);
    homeLayout.announce(t('dashboards.save_failed'));
    return false;
  }
}

function noteViewEdit(): void {
  viewDirty = true;
  viewEdit += 1;
  if (viewTimer !== undefined) clearTimeout(viewTimer);
  viewTimer = setTimeout(() => {
    viewTimer = undefined;
    void saveViewBoard();
  }, WRITE_DELAY);
}

async function saveViewBoard(): Promise<void> {
  const carried = viewEdit;
  const saved = await putBoard(viewingId);
  if (!saved || carried === viewEdit) viewDirty = false;
}

export async function viewBoard(id: string | null): Promise<void> {
  if (popoutMode) return;
  const target = id && id !== activeId && boards.some((board) => board.id === id) ? id : null;
  if (target === viewingId) return;
  if (viewTimer !== undefined) clearTimeout(viewTimer);
  viewTimer = undefined;
  if (viewDirty) await saveViewBoard();
  await flushHome();
  const leaving = shownId;
  const live = liveLayout();
  boards = boards.map((board) => (board.id === leaving ? { ...board, layout: live } : board));
  viewingId = target;
  if (!known) {
    publishBoards();
    return;
  }
  applyHome({ v: 2, boards, analytics_seed: synced?.analytics_seed ?? 0, active: activeId });
}

async function migrate(api: PreferencesApi): Promise<void> {
  known = true;
  let stored = false;
  try {
    stored = localStorage.getItem(STORAGE_KEYS.home) !== null;
  } catch {
  }
  if (!stored) return;
  const mine = current();
  inflight = true;
  try {
    const result = await api.set(HOME_LAYOUT_FIELD, mine);
    if (result.status === 'committed' || result.status === 'unchanged') remember(mine);
    else if (result.status === 'stale_revision') {
      const theirs = parseHome(api.committedValue(HOME_LAYOUT_FIELD));
      if (theirs) applyHome(theirs);
    }
  } catch (error) {
    console.warn('[home layout] migration failed', error);
    known = false;
  } finally {
    inflight = false;
  }
  if (wantsWrite()) scheduleWrite();
}

export async function hydrateHome(): Promise<void> {
  const api = preferencesApi();
  if (!api) {
    seedControl.markReady();
    return;
  }
  if (api.status() !== api.HYDRATED || inflight) return;
  const value = parseHome(api.committedValue(HOME_LAYOUT_FIELD));
  if (value) applyHome(value);
  else if (!known) await migrate(api);
  seedControl.markReady();
  if (wantsWrite()) scheduleWrite();
}

async function pullServer(): Promise<void> {
  try {
    const block = await authFetch<{ values?: Record<string, unknown> }>('/preferences');
    const value = parseHome(block.values?.[HOME_LAYOUT_FIELD]);
    if (value) applyHome(value);
  } catch (error) {
    console.warn('[home layout] pop-out read failed', error);
  }
}

export function startHomeSync(options: { popout?: boolean; board?: string | null; edit?: boolean; target?: Window | null } = {}): void {
  if (started) return;
  started = true;
  popoutMode = options.popout === true;
  wallboardId = options.board ?? null;
  popoutEdits = popoutMode && options.edit === true && wallboardId !== null;
  const target = options.target === undefined ? (typeof window !== 'undefined' ? window : null) : options.target;
  if (popoutMode) {
    if (popoutEdits) stops.push(onHomeChange(notePopoutEdit));
    void pullServer();
    stops.push(subscribe('preferences.changed', () => void pullServer()));
    stops.push(subscribe('events.hello', () => void pullServer()));
    const onVisible = (): void => {
      if (target?.document?.visibilityState === 'visible') void pullServer();
    };
    target?.document?.addEventListener('visibilitychange', onVisible);
    stops.push(() => target?.document?.removeEventListener('visibilitychange', onVisible));
    return;
  }
  seedControl.attach(() => scheduleWrite(), referencedAnalytics);
  stops.push(onHomeChange(noteLocal));
  const api = preferencesApi();
  if (api) {
    stops.push(
      api.subscribe((name, value, record) => {
        if (name !== HOME_LAYOUT_FIELD || record?.state !== api.COMMITTED || inflight) return;
        const next = parseHome(value);
        if (next) applyHome(next);
      }),
    );
  }
  whenLegacyBootComplete(target, () => void hydrateHome());
  const onVisible = (): void => {
    if (target?.document?.visibilityState === 'visible') void hydrateHome();
  };
  target?.document?.addEventListener('visibilitychange', onVisible);
  stops.push(() => target?.document?.removeEventListener('visibilitychange', onVisible));
}

export function resetHomeSync(): void {
  for (const stop of stops) stop();
  stops = [];
  started = false;
  popoutMode = false;
  synced = null;
  known = false;
  boards = [];
  activeId = HOME_BOARD_ID;
  shownId = HOME_BOARD_ID;
  viewingId = null;
  viewDirty = false;
  viewEdit = 0;
  activeChosen = false;
  wallboardId = null;
  popoutEdits = false;
  popoutEdit = 0;
  publishBoards();
  dirty = false;
  held = null;
  applying = false;
  inflight = false;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  if (heldTimer !== undefined) clearTimeout(heldTimer);
  if (viewTimer !== undefined) clearTimeout(viewTimer);
  viewTimer = undefined;
  writeTimer = undefined;
  heldTimer = undefined;
  seedControl.reset();
}
