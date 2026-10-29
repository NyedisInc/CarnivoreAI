
import type { CellId, InstanceKind, Layout, LayoutPage, MetaMap, Reservation, RowId, RowModel, Slot, SlotId } from './types';
import { isPluginSlot } from './plugin-kinds';
import { INSTANCE_KINDS, META, instanceId, isInstanceId, kindOf, metaFor } from './meta';
import { FIT_DECLARATIONS } from '../widgets/fit-declarations';
import { clearSpan, repairSpans, visualOrder } from './spans';
import { sharePixels } from './tracks';
import { COL_MIN, ROW_MIN } from './floors';

export const ROW_MAX = 1600;

/* already exists */
export const MAX_VIEWERS = 6;

export const PRIMARY_SLOT = 'terminal:@primary';

export function insertAnalyticsRow(layout: Layout, ids: readonly SlotId[], limits: LimitMap = DECLARED_LIMITS): Layout {
  if (!ids.length || layout.rows.some((row) => row.kind !== 'px')) return layout;
  if (limitVerdict(layout, 'analytics', ids.length, limits).refused) return layout;
  const known = new Set([...layout.hidden, ...layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))]);
  const chartId = /^analytics:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (ids.some((id) => !chartId.test(id) || known.has(id)) || new Set(ids).size !== ids.length) return layout;
  let at = 0;
  while (at < layout.rows.length && (
    layout.rows.slice(0, at).some((row, start) => row.slots.some((slot) => start + (slot.span ?? 1) > at))
    || layout.rows[at]?.slots.every((slot) => slot.id.startsWith('analytics:')))) at += 1;
  const nextNumber = Math.max(0, ...layout.rows.map((row) => Number(row.id.slice(1)))) + 1;
  const added: RowModel[] = [];
  for (let start = 0; start < ids.length; start += 2) {
    const pair = ids.slice(start, start + 2);
    added.push({ id: `r${nextNumber + added.length}`, kind: 'px', size: 280,
      slots: pair.map((id) => ({ id, fr: 1 / pair.length })) });
  }
  return { ...layout, rows: [...layout.rows.slice(0, at), ...added, ...layout.rows.slice(at)] };
}

const DEFAULT_CHART_ROWS = [
  { size: 223.52, frs: [0.6667, 0.3333] },
  { size: 252.42, frs: [0.3339, 0.3333, 0.3328] },
] as const;

export function insertDefaultAnalytics(layout: Layout, ids: readonly SlotId[]): Layout {
  const strip = layout.rows.findIndex((row) => row.slots.some((slot) => slot.id === 'stat-running'));
  const total = DEFAULT_CHART_ROWS.reduce((sum, row) => sum + row.frs.length, 0);
  const fresh = JSON.stringify(layout.rows) === JSON.stringify(resetLayout().rows);
  if (strip < 0 || ids.length !== total || !fresh || layout.rows.some((row) => row.kind !== 'px')) return insertAnalyticsRow(layout, ids);
  const known = new Set([...layout.hidden, ...layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))]);
  const chartId = /^analytics:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (ids.some((id) => !chartId.test(id) || known.has(id)) || layout.rows.slice(0, strip + 1).some((row, start) => row.slots.some((slot) => start + (slot.span ?? 1) > strip + 1))) return insertAnalyticsRow(layout, ids);
  const nextNumber = Math.max(0, ...layout.rows.map((row) => Number(row.id.slice(1)))) + 1;
  let taken = 0;
  const added: RowModel[] = DEFAULT_CHART_ROWS.map((row, at) => {
    const slots = row.frs.flatMap((fr) => {
      const id = ids[taken++];
      return id === undefined ? [] : [{ id, fr }];
    });
    return { id: `r${nextNumber + at}`, kind: 'px', size: row.size, slots };
  });
  return { ...layout, rows: [...layout.rows.slice(0, strip + 1), ...added, ...layout.rows.slice(strip + 1)] };
}

export function normalizeRow(row: RowModel): RowModel {
  const slots = row.slots.filter((slot) => Number.isFinite(slot.fr) && slot.fr > 0);
  const total = slots.reduce((sum, slot) => sum + slot.fr, 0);
  if (!slots.length) return { ...row, slots: [] };
  if (slots.length === row.slots.length && Math.abs(total - 1) < 1e-9) return row;
  const scale = total > 0 ? 1 / total : 1 / slots.length;
  return { ...row, slots: slots.map((slot) => ({ ...slot, fr: total > 0 ? slot.fr * scale : scale })) };
}

function withRow(layout: Layout, rowId: RowId, next: RowModel): Layout {
  return { ...layout, rows: layout.rows.map((row) => (row.id === rowId ? next : row)) };
}

export function rowOf(layout: Layout, rowId: RowId): RowModel | undefined {
  return layout.rows.find((row) => row.id === rowId);
}

export function rowOfCell(layout: Layout, id: SlotId): RowModel | undefined {
  return layout.rows.find((row) => row.slots.some((slot) => slot.id === id));
}

export function rowFloor(_row: RowModel, _metas: MetaMap = META): number {
  return ROW_MIN;
}

const ROW_OPEN_MIN = 44;

export function rowHeightFor(slots: readonly SlotId[], metas: MetaMap = META): number {
  return slots.reduce((carry, id) => Math.max(carry, metaFor(id, metas).defaultHeight), ROW_OPEN_MIN);
}

export function resizeColumns(
  layout: Layout,
  rowId: RowId,
  index: number,
  dxPx: number,
  freePx: number,
  leftMinPx: number,
  leftMaxPx: number,
): Layout {
  const row = rowOf(layout, rowId);
  if (!row || index < 0 || index >= row.slots.length - 1) return layout;
  const left = row.slots[index];
  const right = row.slots[index + 1];
  if (!left || !right) return layout;
  const space = Math.max(1, freePx);
  const low = leftMinPx / space;
  const high = leftMaxPx / space;
  if (high < low) return layout;
  const breaks = new Set((row.reserved ?? []).map((one) => one.at));
  const floor = COL_MIN / space;
  const slots = row.slots.slice();
  const room = (at: number): number => Math.max(0, slots[at]!.fr - floor);
  const rightRun: number[] = [];
  for (let at = index + 1; at < slots.length && (at === index + 1 || !breaks.has(at)); at += 1) rightRun.push(at);
  const leftRun: number[] = [];
  for (let at = index; at >= 0 && (at === index || !breaks.has(at + 1)); at -= 1) leftRun.push(at);
  const sum = (run: number[]): number => run.reduce((carry, at) => carry + room(at), 0);
  const most = Math.max(0, Math.min(high - left.fr, sum(rightRun)));
  const least = Math.min(0, Math.max(low - left.fr, -sum(leftRun)));
  const move = Math.min(Math.max(dxPx / space, least), most);
  if (move === 0) return layout;
  let want = Math.abs(move);
  const takerAt = move > 0 ? index : index + 1;
  for (const at of move > 0 ? rightRun : leftRun) {
    if (want <= 0) break;
    const take = Math.min(want, room(at));
    slots[at] = { ...slots[at]!, fr: slots[at]!.fr - take };
    want -= take;
  }
  slots[takerAt] = { ...slots[takerAt]!, fr: slots[takerAt]!.fr + Math.abs(move) - want };
  return withRow(layout, rowId, { ...row, slots });
}

export function resizeRows(
  layout: Layout,
  aboveId: RowId,
  dyPx: number,
  flexSpacePx: number,
  metas: MetaMap = META,
): Layout {
  const above = rowOf(layout, aboveId);
  if (!above) return layout;
  if (above.kind === 'px') {
    const size = Math.min(ROW_MAX, Math.max(above.size + dyPx, Math.min(above.size, rowFloor(above, metas))));
    return size === above.size ? layout : withRow(layout, aboveId, { ...above, size });
  }
  const flex = layout.rows.filter((row) => row.kind === 'flex');
  const at = flex.findIndex((row) => row.id === aboveId);
  if (at < 0 || at >= flex.length - 1 || dyPx === 0) return layout;
  const space = Math.max(1, flexSpacePx);
  const min = ROW_MIN / space;
  const givers = dyPx > 0 ? flex.slice(at + 1) : flex.slice(0, at + 1).reverse();
  const taker = dyPx > 0 ? flex[at]! : flex[at + 1]!;
  let want = Math.abs(dyPx) / space;
  let got = 0;
  const sizes = new Map<RowId, number>();
  for (const row of givers) {
    if (want <= 0) break;
    const take = Math.min(want, Math.max(0, row.size - min));
    if (take <= 0) continue;
    sizes.set(row.id, row.size - take);
    want -= take;
    got += take;
  }
  if (got === 0) return layout;
  sizes.set(taker.id, taker.size + got);
  return { ...layout, rows: layout.rows.map((row) => (sizes.has(row.id) ? { ...row, size: sizes.get(row.id)! } : row)) };
}

export function resizeIntersection(
  layout: Layout,
  aboveId: RowId,
  index: number,
  dxPx: number,
  dyPx: number,
  freePx: number,
  leftMinPx: number,
  leftMaxPx: number,
  flexSpacePx: number,
  metas: MetaMap = META,
): Layout {
  return resizeCorner(layout, aboveId, index, aboveId, dxPx, dyPx, freePx, leftMinPx, leftMaxPx, flexSpacePx, metas);
}

export function resizeCorner(
  layout: Layout,
  seamRowId: RowId,
  index: number,
  boundaryId: RowId,
  dxPx: number,
  dyPx: number,
  freePx: number,
  leftMinPx: number,
  leftMaxPx: number,
  flexSpacePx: number,
  metas: MetaMap = META,
): Layout {
  return resizeRows(
    resizeColumns(layout, seamRowId, index, dxPx, freePx, leftMinPx, leftMaxPx),
    boundaryId,
    dyPx,
    flexSpacePx,
    metas,
  );
}

export function withoutCell(row: RowModel, id: SlotId): RowModel {
  const at = row.slots.findIndex((slot) => slot.id === id);
  if (at < 0) return row;
  const slots = row.slots.filter((slot) => slot.id !== id);
  const held = row.reserved;
  if (!held || held.length === 0) return { ...row, slots };
  return { ...row, slots, reserved: held.map((one) => (one.at > at ? { ...one, at: one.at - 1 } : one)) };
}

function shiftedForInsert(row: RowModel, at: number, visual?: number): Reservation[] | undefined {
  const held = row.reserved;
  if (!held || held.length === 0) return undefined;
  const order = visual === undefined ? [] : visualOrder(row);
  return held.map((one) => {
    if (one.at < at) return one;
    if (one.at === at && visual !== undefined) {
      const drawnAt = order.findIndex((entry) => entry.kind === 'reserved' && entry.of === one.of);
      if (drawnAt >= 0 && drawnAt < visual) return one;
    }
    return { ...one, at: one.at + 1 };
  });
}

export function moveCell(layout: Layout, id: SlotId, toRow: RowId, toVisual: number): Layout {
  const base = clearSpan(layout, id);
  const from = rowOfCell(base, id);
  const target = rowOf(base, toRow);
  if (!from || !target) return layout;
  const moving = from.slots.find((slot) => slot.id === id);
  if (!moving) return layout;
  const toIndex = slotIndexOfVisual(target, toVisual);
  if (from.id === toRow) {
    const fromIndex = from.slots.indexOf(moving);
    const fromVisual = visualOrder(from).findIndex((entry) => entry.kind === 'slot' && entry.slot.id === id);
    const gone = withoutCell(from, id);
    const rest = gone.slots.slice();
    const at = Math.min(Math.max(fromIndex < toIndex ? toIndex - 1 : toIndex, 0), rest.length);
    rest.splice(at, 0, moving);
    const held = shiftedForInsert(gone, at, fromVisual < toVisual ? toVisual - 1 : toVisual);
    const next = held ? { ...gone, slots: rest, reserved: held } : { ...gone, slots: rest };
    return repairSpans(withRow(base, toRow, normalizeRow(next)));
  }
  const count = target.slots.length;
  const share = 1 / (count + 1);
  const scaled: Slot[] = target.slots.map((slot) => ({ ...slot, fr: slot.fr * (count / (count + 1)) }));
  const at = Math.min(Math.max(toIndex, 0), scaled.length);
  scaled.splice(at, 0, { id, fr: share });
  const held = shiftedForInsert(target, at, toVisual);
  const rows = base.rows.map((row) => {
    if (row.id === from.id) return normalizeRow(withoutCell(row, id));
    if (row.id === toRow) return held ? { ...row, slots: scaled, reserved: held } : { ...row, slots: scaled };
    return row;
  });
  return repairSpans({ ...base, rows });
}

export function slotIndexOfVisual(row: RowModel, visual: number): number {
  const order = visualOrder(row);
  const upto = Math.min(Math.max(visual, 0), order.length);
  let at = 0;
  for (let index = 0; index < upto; index += 1) {
    if (order[index]?.kind === 'slot') at += 1;
  }
  return at;
}

export function freeRowId(layout: Layout): RowId {
  let highest = 0;
  for (const row of layout.rows) {
    const match = /^r([1-9][0-9]*)$/.exec(row.id);
    if (match) highest = Math.max(highest, Number(match[1]));
  }
  return `r${highest + 1}` as RowId;
}

export function moveCellToNewRow(layout: Layout, id: SlotId, after: RowId | null, metas: MetaMap = META): Layout {
  const base = clearSpan(layout, id);
  const from = rowOfCell(base, id);
  if (!from) return layout;
  const fromAt = base.rows.findIndex((row) => row.id === from.id);
  const afterAt = after === null ? -1 : base.rows.findIndex((row) => row.id === after);
  if (from.slots.length === 1 && fromAt === afterAt + 1) return layout;
  const minted: RowModel = {
    id: freeRowId(base),
    kind: base.rows[0]?.kind ?? 'px',
    size: base.rows[0]?.kind === 'flex' ? 1 : rowHeightFor([id], metas),
    slots: [{ id, fr: 1 }],
  };
  const rows: RowModel[] = [];
  if (after === null) rows.push(minted);
  for (const row of base.rows) {
    rows.push(row.id === from.id ? normalizeRow(withoutCell(row, id)) : row);
    if (row.id === after) rows.push(minted);
  }
  const flexCount = rows.filter((one) => one.kind === 'flex').length;
  const kept = base.rows.reduce((sum, one) => (one.kind === 'flex' ? sum + one.size : sum), 0);
  const shared =
    minted.kind === 'flex'
      ? rows.map((row) =>
          row.id === minted.id
            ? { ...row, size: 1 / flexCount }
            : row.kind === 'flex' && kept > 0
              ? { ...row, size: (row.size / kept) * (1 - 1 / flexCount) }
              : row,
        )
      : rows;
  return repairSpans({ ...base, rows: shared });
}

/*  hidden  */
export function hideCell(layout: Layout, id: SlotId): Layout {
  if (isInstanceId(id) && !id.startsWith('analytics:')) return layout;
  if (layout.hidden.includes(id)) return layout;
  const base = clearSpan(layout, id);
  const from = rowOfCell(base, id);
  if (!from) return layout;
  const rows = base.rows.map((row) =>
    row.id === from.id ? normalizeRow(withoutCell(row, id)) : row,
  );
  return repairSpans({ ...base, rows, hidden: [...base.hidden, id] });
}

/*  hidden  */
export function showCell(layout: Layout, id: SlotId, metas: MetaMap = META): Layout {
  const placed = layout.rows.some((row) => row.slots.some((slot) => slot.id === id));
  if (placed || (!layout.hidden.includes(id) && !(id in metas))) return layout;
  const meta = metaFor(id, metas);
  const hidden = layout.hidden.filter((other) => other !== id);
  const home = rowOf(layout, meta.defaultRow);
  if (home) {
    const count = home.slots.length;
    const wanted = meta.defaultFr;
    const usable = count === 0 || (wanted > 0 && wanted < 1);
    const share = count === 0 ? 1 : usable ? wanted : 1 / (count + 1);
    const room = 1 - share;
    const total = home.slots.reduce((sum, slot) => sum + slot.fr, 0);
    const scaled: Slot[] = home.slots.map((slot) => ({
      ...slot,
      fr: total > 0 ? (slot.fr / total) * room : room / count,
    }));
    const at = Math.min(Math.max(meta.defaultIndex, 0), scaled.length);
    scaled.splice(at, 0, { id, fr: share });
    return repairSpans({ ...withRow(layout, meta.defaultRow, { ...home, slots: scaled }), hidden });
  }
  const last = layout.rows[layout.rows.length - 1];
  if (!last) return { ...layout, hidden };
  return repairSpans({ ...moveIntoRow(layout, id, last.id), hidden });
}

function moveIntoRow(layout: Layout, id: SlotId, rowId: RowId): Layout {
  const row = rowOf(layout, rowId);
  if (!row) return layout;
  const count = row.slots.length;
  const scaled = row.slots.map((slot) => ({ ...slot, fr: slot.fr * (count / (count + 1)) }));
  const slots = [...scaled, { id, fr: 1 / (count + 1) }];
  const held = shiftedForInsert(row, count);
  return withRow(layout, rowId, held ? { ...row, slots, reserved: held } : { ...row, slots });
}

export function resetRow(layout: Layout, rowId: RowId, metas: MetaMap = META): Layout {
  const row = rowOf(layout, rowId);
  if (!row) return layout;
  const slots = row.slots.map((slot) => ({ ...slot, fr: metaFor(slot.id, metas).defaultFr }));
  return withRow(layout, rowId, normalizeRow({ ...row, slots }));
}

export function resetHeights(layout: Layout, metas: MetaMap = META): Layout {
  return {
    ...layout,
    rows: layout.rows.map((row) => {
      if (row.kind !== 'px' || row.slots.length === 0) return row;
      return { ...row, size: rowHeightFor(row.slots.map((slot) => slot.id), metas) };
    }),
  };
}

export function setRowHeight(layout: Layout, rowId: RowId, px: number, metas: MetaMap = META): Layout {
  const row = rowOf(layout, rowId);
  if (!row || row.kind !== 'px') return layout;
  const size = Math.min(Math.max(Math.round(px), Math.min(row.size, rowFloor(row, metas))), ROW_MAX);
  if (size === row.size) return layout;
  return withRow(layout, rowId, { ...row, size });
}

export function fitRows(layout: Layout, availablePx: number, gutter: number, metas: MetaMap = META): Layout {
  const pxRows = layout.rows.filter((row) => row.kind === 'px');
  if (!pxRows.length || availablePx <= 0) return layout;
  const budget = Math.max(1, Math.floor(availablePx) - gutter * Math.max(0, layout.rows.length - 1));
  const shares = sharePixels(pxRows.map((row) => Math.max(1, row.size)), budget);
  let at = 0;
  return {
    ...layout,
    rows: layout.rows.map((row) => {
      if (row.kind !== 'px') return row;
      const size = Math.max(Math.min(row.size, rowFloor(row, metas)), Math.min(shares[at] ?? row.size, ROW_MAX));
      at += 1;
      return { ...row, size };
    }),
  };
}

/*  hidden  */
export const HIDDEN_BY_DEFAULT: readonly CellId[] = ['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects'];

/*  hidden  */
export function offSurfaceIds(layout: Layout): SlotId[] {
  const missing = HIDDEN_BY_DEFAULT.filter(
    (id) => !layout.hidden.includes(id) && rowOfCell(layout, id) === undefined,
  );
  return [...layout.hidden, ...missing];
}

export function resetLayout(metas: MetaMap = META, page: LayoutPage = 'home'): Layout {
  if (page === 'warroom') {
    return {
      v: 6,
      rows: [{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: 'warroom', fr: 1 }] }],
      hidden: HIDDEN_BY_DEFAULT.filter((id) => id !== 'warroom'),
      heroCollapsed: false,
      collapsed: [],
    };
  }
  if (page === 'terminal') {
    return {
      v: 6,
      rows: [{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: 'terminal:@primary', fr: 1 }] }],
      hidden: [...HIDDEN_BY_DEFAULT],
      heroCollapsed: false,
      collapsed: [],
    };
  }
  const placed = (Object.keys(metas) as CellId[]).filter((id) => !HIDDEN_BY_DEFAULT.includes(id));
  const ids = [...new Set(placed.map((id) => metas[id].defaultRow))].sort(
    (a, b) => Number(a.slice(1)) - Number(b.slice(1)),
  );
  const rows: RowModel[] = ids.map((rowId) => {
    const slots = placed
      .filter((id) => metas[id].defaultRow === rowId)
      .sort((a, b) => metas[a].defaultIndex - metas[b].defaultIndex)
      .map((id) => ({ id, fr: metas[id].defaultFr }));
    return normalizeRow({
      id: rowId,
      kind: 'px',
      size: rowHeightFor(slots.map((slot) => slot.id), metas),
      slots,
    });
  });
  const collapsed = (Object.keys(metas) as CellId[]).filter((id) => metas[id].phoneCollapsedByDefault === true);
  return { v: 6, rows, hidden: [...HIDDEN_BY_DEFAULT], heroCollapsed: false, collapsed };
}

export const DEFAULT_LAYOUT: Layout = resetLayout();


export type AddRefusal = null | 'duplicate' | 'cap' | 'limit' | 'no-row';

export interface AddResult {
  layout: Layout;
  refusal: AddRefusal;
}

function slotsInReadingOrder(layout: Layout): SlotId[] {
  const out: SlotId[] = [];
  for (const row of layout.rows) {
    for (const slot of row.slots) out.push(slot.id);
  }
  return out;
}

/*  hidden  */
export function instancesOf(layout: Layout): SlotId[] {
  const placed = slotsInReadingOrder(layout).filter(isInstanceId);
  return [...placed, ...layout.hidden.filter(isInstanceId)];
}

export function viewersOf(layout: Layout): SlotId[] {
  return instancesOf(layout).filter((id) => id !== PRIMARY_SLOT && !id.startsWith('analytics:') && !isPluginSlot(id));
}

export type LimitMap = Readonly<Partial<Record<InstanceKind, number>>>;

export const DECLARED_LIMITS: LimitMap = Object.freeze(
  Object.fromEntries(
    INSTANCE_KINDS.flatMap((kind) => {
      const limit = FIT_DECLARATIONS[kind]?.max_per_surface;
      return limit === undefined ? [] : [[kind, limit]];
    }),
  ) as LimitMap,
);

export function copiesOf(layout: Layout, kind: InstanceKind): SlotId[] {
  return instancesOf(layout).filter((id) => id !== PRIMARY_SLOT && kindOf(id) === kind);
}

export interface LimitVerdict {
  refused: boolean;
  limit: number | undefined;
  moves: SlotId | null;
}

export function limitVerdict(layout: Layout, kind: InstanceKind, adding = 1, limits: LimitMap = DECLARED_LIMITS): LimitVerdict {
  const limit = limits[kind];
  if (limit === undefined) return { refused: false, limit, moves: null };
  const held = copiesOf(layout, kind);
  return { refused: held.length + adding > limit, limit, moves: limit === 1 && held.length === 1 ? held[0]! : null };
}

export function addInstance(
  layout: Layout,
  kind: InstanceKind,
  sessionId: string,
  currentPrimarySessionId: string,
  metas: MetaMap = META,
  limits: LimitMap = DECLARED_LIMITS,
): AddResult {
  void metas;
  const id = instanceId(kind, sessionId);
  if (slotsInReadingOrder(layout).includes(id) || layout.hidden.includes(id)) {
    return { layout, refusal: 'duplicate' };
  }
  const wanted = sessionId.trim();
  const primary = (currentPrimarySessionId ?? '').trim();
  if (primary !== '' && primary === wanted) return { layout, refusal: 'duplicate' };
  if (limitVerdict(layout, kind, 1, limits).refused) return { layout, refusal: 'limit' };
  if (kind !== 'analytics' && !isPluginSlot(kind) && viewersOf(layout).length >= MAX_VIEWERS) return { layout, refusal: 'cap' };
  const last = layout.rows[layout.rows.length - 1];
  if (!last) return { layout, refusal: 'no-row' };
  return { layout: repairSpans(moveIntoRow(layout, id, last.id)), refusal: null };
}

/*  hidden  */
export function removeCell(layout: Layout, id: SlotId): Layout {
  if (id === PRIMARY_SLOT) return layout;
  const base = clearSpan(layout, id);
  const from = rowOfCell(base, id);
  if (!from) return layout;
  const rows = base.rows.map((row) =>
    row.id === from.id ? normalizeRow(withoutCell(row, id)) : row,
  );
  const { headerOff: held, ...rest } = base;
  const headerOff = held?.filter((one) => one !== id);
  return repairSpans({ ...rest, rows, ...(headerOff?.length ? { headerOff } : {}) });
}

function withRows(layout: Layout, groups: SlotId[][], metas: MetaMap): Layout {
  const filled = groups.filter((group) => group.length > 0);
  if (!filled.length) return layout;
  const kind: RowModel['kind'] = layout.rows[0]?.kind ?? 'px';
  const share = 1 / filled.length;
  const rows: RowModel[] = filled.map((group, index) => ({
    id: `r${index + 1}` as RowId,
    kind,
    size: kind === 'flex' ? share : rowHeightFor(group, metas),
    slots: group.map((id) => ({ id, fr: 1 / group.length })),
  }));
  return { ...layout, rows };
}

export function arrangeColumns(layout: Layout, metas: MetaMap = META): Layout {
  const slots = slotsInReadingOrder(layout);
  if (!slots.length) return layout;
  return withRows(layout, [slots], metas);
}

export function arrangeRows(layout: Layout, metas: MetaMap = META): Layout {
  const slots = slotsInReadingOrder(layout);
  if (!slots.length) return layout;
  return withRows(layout, slots.map((id) => [id]), metas);
}

export function arrangeGrid(layout: Layout, metas: MetaMap = META): Layout {
  const slots = slotsInReadingOrder(layout);
  if (!slots.length) return layout;
  const cols = Math.ceil(Math.sqrt(slots.length));
  const groups: SlotId[][] = [];
  for (let at = 0; at < slots.length; at += cols) groups.push(slots.slice(at, at + cols));
  return withRows(layout, groups, metas);
}

export const ARRANGERS: Readonly<Record<'columns' | 'rows' | 'grid', (layout: Layout, metas?: MetaMap) => Layout>> = {
  columns: arrangeColumns,
  rows: arrangeRows,
  grid: arrangeGrid,
};

export type ArrangeMode = keyof typeof ARRANGERS;
