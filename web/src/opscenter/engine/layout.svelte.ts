
import {
  ARRANGERS,
  addInstance,
  fitRows,
  hideCell,
  insertAnalyticsRow,
  insertDefaultAnalytics,
  removeCell,
  resetHeights,
  resetLayout,
  resetRow,
  resizeColumns,
  resizeCorner,
  resizeIntersection,
  resizeRows,
  setRowHeight,
  showCell,
  offSurfaceIds,
  type AddRefusal,
  type ArrangeMode,
} from './model';
import { spanUp } from './spans';
import { setCellSize, sizeRefusal } from './cell-size';
import { computeTracks } from './tracks';
import type { FitSize } from '../widgets/types';
import type { StackEdge } from './stack';
import type { ColumnDrop } from './column';
import { applyDrop } from './drop';
import { showAt } from '../layout-editor/show-at';
import { canSpanDown, spanDown, type SpanRefusal } from './span-extend';
import { META, instanceId, metaFor } from './meta';
import { headerShown } from '../shell/widget-head';
import { clear, flushSave, load, save, validate } from './persist';
import { arrangementChanged, homeChanged, warroomChanged } from './arrangement-events';
import { abandonGesture } from './pointer';
import { forgetSession, isBareTerminal, isLayoutKey, layoutKey, openSessionLayout, touchSession } from './session-layouts';
import { primarySessionId } from '../api/host';
import { sessions } from '../api';
import { sessionForSlot } from './slot-identity';
import type { CellId, CellMeta, InstanceKind, Layout, LayoutPage, RowId, SlotId } from './types';
import { coreWidgetId } from '../widgets/core-manifests';
import { isWidgetDisabled } from '../../lib/item-settings/store.svelte';

export interface LayoutState {
  layout: Layout;
  warning: string;
  announcement: string;
}

export type DropTarget =
  | { kind: 'row'; row: RowId; index: number }
  | { kind: 'new'; after: RowId | null }
  | { kind: 'stack'; of: SlotId; edge: StackEdge }
  | ColumnDrop;

export interface DragState {
  id: SlotId | null;
  dx: number;
  dy: number;
  target: DropTarget | null;
}

export interface LayoutStore {
  readonly page: LayoutPage;
  readonly session: string;
  bindSession(tmuxName: string, tmuxEpoch?: number | null): boolean;
  bindKey(key: string, layout: Layout): boolean;
  readonly state: LayoutState;
  readonly drag: DragState;
  announce(line: string): void;
  announceLater(line: string): void;
  setWarning(line: string): void;
  hiddenCells(): CellMeta[];
  dragColumns(
    snapshot: Layout,
    rowId: RowId,
    index: number,
    dxPx: number,
    freePx: number,
    leftMinPx: number,
    leftMaxPx: number,
  ): void;
  dragRows(snapshot: Layout, aboveId: RowId, dyPx: number, flexSpacePx: number): void;
  dragIntersection(
    snapshot: Layout,
    aboveId: RowId,
    index: number,
    dxPx: number,
    dyPx: number,
    freePx: number,
    leftMinPx: number,
    leftMaxPx: number,
    flexSpacePx: number,
  ): void;
  dragCorner(
    snapshot: Layout,
    seamRowId: RowId,
    index: number,
    boundaryId: RowId,
    dxPx: number,
    dyPx: number,
    freePx: number,
    leftMinPx: number,
    leftMaxPx: number,
    flexSpacePx: number,
  ): void;
  snapshot(): Layout;
  restore(snapshot: Layout): void;
  beginDraft(): void;
  endDraft(saveDraft: boolean): void;
  adopt(layout: Layout | null): boolean;
  moveTo(id: SlotId, target: DropTarget): boolean;
  showAt(id: SlotId, target: DropTarget): 'landed' | 'placed' | 'unchanged';
  spanDown(id: SlotId, widthPx: number, gutter: number): boolean;
  spanUp(id: SlotId): void;
  spanRefusal(id: SlotId, widthPx: number, gutter: number): SpanRefusal;
  fitRows(availablePx: number, gutter: number): void;
  setRowHeight(rowId: RowId, px: number): void;
  setCellSize(id: SlotId, size: FitSize, widthPx: number, gutter: number): boolean;
  hide(id: SlotId): void;
  remove(id: SlotId): void;
  show(id: SlotId): void;
  add(kind: InstanceKind, sessionId: string): AddRefusal;
  insertAnalytics(ids: readonly SlotId[], first?: boolean): boolean;
  arrange(mode: ArrangeMode): void;
  resetOneRow(rowId: RowId): void;
  resetRowHeights(): void;
  resetAll(availablePx?: number, gutter?: number): void;
  setHeroCollapsed(collapsed: boolean): void;
  isCollapsed(id: SlotId): boolean;
  toggleCollapsed(id: SlotId): void;
  isHeaderShown(id: SlotId): boolean;
  setHeaderShown(id: SlotId, shown: boolean): void;
  clearDrag(): void;
}

export function createLayoutStore(page: LayoutPage): LayoutStore {
  const opened =
    page === 'terminal'
      ? { layout: resetLayout(META, 'terminal'), notice: '', stored: false }
      : load(META, page, primarySessionId());
  if (page === 'home' && opened.migrated) save(opened.layout, page);

  const state: LayoutState = $state({
    layout: opened.layout,
    warning: opened.notice,
    announcement: '',
  });

  const drag: DragState = $state({ id: null, dx: 0, dy: 0, target: null });

  let session = '';
  let epoch = 0;
  const taken = new WeakMap<Layout, number>();

  function current(snapshot: Layout): boolean {
    return taken.get(snapshot) === epoch;
  }
  let indexed = false;
  let drafting = false;

  function persist(next: Layout): void {
    if (page !== 'terminal') {
      save(next, page);
      if (page === 'warroom') warroomChanged();
      else homeChanged();
      return;
    }
    if (!session) return;
    if (isLayoutKey(session)) {
      arrangementChanged(session);
      return;
    }
    if (isBareTerminal(next)) {
      forgetSession(session);
      indexed = false;
    } else {
      save(next, page, session);
      if (!indexed) {
        touchSession(session);
        indexed = true;
      }
    }
    arrangementChanged(session);
  }

  function commit(next: Layout): void {
    if (next === state.layout) return;
    state.layout = next;
    if (!drafting) persist(next);
  }

  let columnTimer: ReturnType<typeof setTimeout> | undefined;

  return {
    page,
    state,
    drag,
    beginDraft(): void { drafting = true; },
    endDraft(saveDraft: boolean): void {
      if (!drafting) return;
      drafting = false;
      if (saveDraft) persist(state.layout);
    },

    get session(): string {
      return session;
    },

    bindSession(tmuxName: string, tmuxEpoch: number | null = null): boolean {
      if (page !== 'terminal') return false;
      const name = (tmuxName ?? '').trim();
      const created = typeof tmuxEpoch === 'number' && Number.isFinite(tmuxEpoch) ? tmuxEpoch : null;
      const key = name ? layoutKey(name, created) : '';
      if (key === session) return false;
      if (drafting) { drafting = false; persist(state.layout); }
      abandonGesture();
      epoch += 1;
      drag.id = null;
      drag.dx = 0;
      drag.dy = 0;
      drag.target = null;
      if (session) flushSave(page, session);
      session = key;
      indexed = false;
      if (!name) {
        state.layout = resetLayout(META, 'terminal');
        state.warning = '';
        return true;
      }
      const opened = openSessionLayout(name, created, META);
      state.layout = opened.layout;
      state.warning = opened.notice;
      if (opened.stored) {
        touchSession(key);
        indexed = true;
      }
      return true;
    },

    bindKey(key: string, layout: Layout): boolean {
      if (page !== 'terminal' || !key) return false;
      if (drafting) { drafting = false; persist(state.layout); }
      epoch += 1;
      drag.id = null;
      drag.dx = 0;
      drag.dy = 0;
      drag.target = null;
      if (session && session !== key && !isLayoutKey(session)) flushSave(page, session);
      session = key;
      indexed = false;
      state.layout = layout;
      state.warning = '';
      return true;
    },

    announce(line: string): void {
      state.announcement = line;
    },

    announceLater(line: string): void {
      if (columnTimer !== undefined) clearTimeout(columnTimer);
      columnTimer = setTimeout(() => {
        state.announcement = line;
      }, 250);
    },

    setWarning(line: string): void {
      state.warning = line;
    },

    hiddenCells(): CellMeta[] {
      return offSurfaceIds(state.layout)
        .filter((id) => !isWidgetDisabled(coreWidgetId(id as CellId)))
        .map((id) => metaFor(id, META));
    },

    snapshot(): Layout {
      const copy = $state.snapshot(state.layout) as Layout;
      taken.set(copy, epoch);
      return copy;
    },

    dragColumns(snapshot, rowId, index, dxPx, freePx, leftMinPx, leftMaxPx): void {
      if (!current(snapshot)) return;
      commit(resizeColumns(snapshot, rowId, index, dxPx, freePx, leftMinPx, leftMaxPx));
    },

    dragRows(snapshot, aboveId, dyPx, flexSpacePx): void {
      if (!current(snapshot)) return;
      commit(resizeRows(snapshot, aboveId, dyPx, flexSpacePx, META));
    },

    dragIntersection(snapshot, aboveId, index, dxPx, dyPx, freePx, leftMinPx, leftMaxPx, flexSpacePx): void {
      if (!current(snapshot)) return;
      commit(
        resizeIntersection(snapshot, aboveId, index, dxPx, dyPx, freePx, leftMinPx, leftMaxPx, flexSpacePx, META),
      );
    },

    dragCorner(snapshot, seamRowId, index, boundaryId, dxPx, dyPx, freePx, leftMinPx, leftMaxPx, flexSpacePx): void {
      if (!current(snapshot)) return;
      commit(
        resizeCorner(snapshot, seamRowId, index, boundaryId, dxPx, dyPx, freePx, leftMinPx, leftMaxPx, flexSpacePx, META),
      );
    },

    restore(snapshot): void {
      if (!current(snapshot)) return;
      commit(snapshot);
    },

    adopt(layout): boolean {
      if (page === 'home' || page === 'warroom') {
        const checked = layout ? validate(layout, META, page, primarySessionId()) : null;
        if (checked?.layout && !checked.refusal) {
          commit(checked.layout);
          return checked.migrated === true;
        }
        return false;
      }
      if (page !== 'terminal' || !session) return false;
      const checked = layout ? validate(layout, META, 'terminal', primarySessionId()) : null;
      commit(checked?.layout && !checked.refusal ? checked.layout : resetLayout(META, 'terminal'));
      return false;
    },

    moveTo(id, target): boolean {
      const next = applyDrop(state.layout, id, target, META);
      if (next === state.layout) return false;
      commit(next);
      return true;
    },

    showAt(id, target): 'landed' | 'placed' | 'unchanged' {
      const result = showAt(state.layout, id, target, META);
      if (result.layout === state.layout) return 'unchanged';
      commit(result.layout);
      return result.landed ? 'landed' : 'placed';
    },

    spanDown(id, widthPx, gutter): boolean {
      const next = spanDown(state.layout, id, widthPx, gutter, META);
      if (next === state.layout) return false;
      commit(next);
      return true;
    },

    spanUp(id): void {
      commit(spanUp(state.layout, id));
    },

    spanRefusal(id, widthPx, gutter): SpanRefusal {
      return canSpanDown(state.layout, id, widthPx, gutter, META);
    },

    fitRows(availablePx, gutter): void {
      commit(fitRows(state.layout, availablePx, gutter, META));
    },

    setRowHeight(rowId, px): void {
      commit(setRowHeight(state.layout, rowId, px, META));
    },

    setCellSize(id, size, widthPx, gutter): boolean {
      const index = state.layout.rows.findIndex((row) => row.slots.some((slot) => slot.id === id));
      if (index < 0 || sizeRefusal(state.layout, id) !== null) return false;
      const tracks = computeTracks({ rows: state.layout.rows, width: widthPx, height: 0, gutter, metas: META });
      commit(setCellSize(state.layout, id, size, tracks.rows[index]?.free ?? 0, META));
      return true;
    },

    hide(id): void {
      commit(hideCell(state.layout, id));
    },

    remove(id): void {
      commit(removeCell(state.layout, id));
    },

    /*  hidden  */
    show(id): void {
      commit(showCell(state.layout, id, META));
    },

    add(kind, sessionId): AddRefusal {
      const primary = primarySessionId().trim();
      if (kind === 'terminal' && primary && sessionForSlot(instanceId(kind, sessionId), sessions.data) === primary) {
        return 'duplicate';
      }
      const result = addInstance(state.layout, kind, sessionId, primary, META);
      if (!result.refusal) commit(result.layout);
      return result.refusal;
    },

    insertAnalytics(ids, first = false): boolean {
      if (page !== 'home') return false;
      const next = (first ? insertDefaultAnalytics : insertAnalyticsRow)(state.layout, ids);
      if (next === state.layout) return false;
      commit(next);
      return true;
    },

    arrange(mode): void {
      commit(ARRANGERS[mode](state.layout, META));
    },

    resetOneRow(rowId): void {
      commit(resetRow(state.layout, rowId, META));
    },

    resetRowHeights(): void {
      if (state.layout.rows[0]?.kind === 'px') {
        commit(resetHeights(state.layout, META));
        return;
      }
      const flex = state.layout.rows.filter((row) => row.kind === 'flex').length;
      commit({
        ...state.layout,
        rows: state.layout.rows.map((row) => (row.kind === 'flex' ? { ...row, size: 1 / flex } : row)),
      });
    },

    resetAll(availablePx = 0, gutter = 0): void {
      const base = resetLayout(META, page);
      if (page === 'terminal') {
        forgetSession(session);
        indexed = false;
      } else clear(page);
      const fitted = availablePx > 0 ? fitRows(base, availablePx, gutter, META) : base;
      state.layout = fitted;
      if (fitted !== base) persist(fitted);
      else if (page === 'home') homeChanged();
      else if (page === 'warroom') warroomChanged();
    },

    setHeroCollapsed(collapsed): void {
      commit({ ...state.layout, heroCollapsed: collapsed });
    },

    isCollapsed(id): boolean {
      return state.layout.collapsed.includes(id);
    },

    toggleCollapsed(id): void {
      const set = state.layout.collapsed;
      const next = set.includes(id) ? set.filter((held) => held !== id) : [...set, id];
      commit({ ...state.layout, collapsed: next });
    },

    isHeaderShown(id): boolean {
      return headerShown('grid', state.layout.headerOff?.includes(id) ? false : undefined);
    },

    setHeaderShown(id, shown): void {
      const held = state.layout.headerOff ?? [];
      const next = shown ? held.filter((one) => one !== id) : held.includes(id) ? held : [...held, id];
      if (next.length === held.length && next.every((one, at) => one === held[at])) return;
      const { headerOff: _old, ...rest } = state.layout;
      commit(next.length ? { ...rest, headerOff: next } : rest);
    },

    clearDrag(): void {
      drag.id = null;
      drag.dx = 0;
      drag.dy = 0;
      drag.target = null;
    },
  };
}

export const homeLayout: LayoutStore = createLayoutStore('home');

export const terminalLayout: LayoutStore = createLayoutStore('terminal');

export const warroomLayout: LayoutStore = createLayoutStore('warroom');
