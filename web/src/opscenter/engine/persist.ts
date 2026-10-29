
import { META, isInstanceId } from './meta';
import { MAX_VIEWERS, PRIMARY_SLOT, ROW_MAX, isViewerSlot, normalizeRow, resetLayout, rowFloor } from './model';
import { dropRetiredCells } from './retired-cells';
import { replaceCells } from './replaced-cells';
import { MAX_SPAN, repairSpans } from './spans';
import { foldSpanOnlyRows } from './compact';
import type { CellId, Layout, LayoutPage, MetaMap, Reservation, RowId, RowKind, RowModel, Slot, SlotId } from './types';
import { readStoredGrid } from './v7/adapt';
import { t } from '../../lib/i18n/index.svelte';

export const STORAGE_KEYS: Readonly<Record<LayoutPage, string>> = {
  home: 'cloudecode.opscenter.layout.v1',
  terminal: 'cloudecode.opscenter.layout.terminal.v1',
  warroom: 'cloudecode.opscenter.layout.warroom.v1',
};

export const SESSION_KEY_PREFIX = 'cloudecode.opscenter.layout.terminal.session.v1:';

export function storageKey(page: LayoutPage, session = ''): string {
  if (page === 'terminal' && session) return SESSION_KEY_PREFIX + session;
  return STORAGE_KEYS[page];
}

export const SCHEMA_VERSION = 6;

export const MAX_BYTES = 16384;

const INSTANCE_ID =
  /^([a-z][a-z0-9-]{0,31}\.[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.:-][A-Za-z0-9_.: -]{0,62}[A-Za-z0-9_.:-]|[a-z][a-z0-9-]{0,31}\.[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.:-]|terminal:(@primary|[A-Za-z0-9_.:-][A-Za-z0-9_.: -]{0,62}[A-Za-z0-9_.:-]|[A-Za-z0-9_.:-])|browser:[0-9a-f]{16}|analytics:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/;

const SAVE_DELAY = 250;

const ROW_ID = /^r[1-9][0-9]*$/;

function rowKind(page: LayoutPage, id: string): RowKind | null {
  if (!ROW_ID.test(id)) return null;
  return page === 'home' ? 'px' : 'flex';
}

function readReserved(raw: unknown): Reservation[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) return null;
  const out: Reservation[] = [];
  for (const entry of raw as unknown[]) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
    const one = entry as Record<string, unknown>;
    const of = one['of'];
    const at = one['at'];
    if (typeof of !== 'string') return null;
    if (typeof at !== 'number' || !Number.isFinite(at) || at < 0) return null;
    out.push({ of: of as SlotId, at: Math.round(at) });
  }
  return out;
}

function slotKind(id: unknown, metas: MetaMap): 'singleton' | 'instance' | null {
  if (typeof id !== 'string') return null;
  if (Object.hasOwn(metas, id)) return 'singleton';
  return INSTANCE_ID.test(id) ? 'instance' : null;
}

export type Refusal =
  | null
  | 'absent'
  | 'unreadable'
  | 'oversize'
  | 'malformed'
  | 'version'
  | 'rows'
  | 'row-id'
  | 'row-kind'
  | 'spans'
  | 'cells'
  | 'primary-duplicate'
  | 'tree';

export interface Validation {
  layout: Layout | null;
  refusal: Refusal;
  repaired: boolean;
  migrated?: boolean;
}

export interface LoadResult {
  layout: Layout;
  notice: string;
  stored: boolean;
  migrated?: boolean;
}

const NOTICE_KEYS: Readonly<Record<Exclude<Refusal, null | 'absent'>, string>> = {
  unreadable: 'opscenter.layout.refusal.unreadable',
  oversize: 'opscenter.layout.refusal.oversize',
  malformed: 'opscenter.layout.refusal.malformed',
  version: 'opscenter.layout.refusal.version',
  rows: 'opscenter.layout.refusal.rows',
  'row-id': 'opscenter.layout.refusal.row_id',
  'row-kind': 'opscenter.layout.refusal.row_kind',
  spans: 'opscenter.layout.refusal.spans',
  cells: 'opscenter.layout.refusal.cells',
  'primary-duplicate': 'opscenter.layout.refusal.primary_duplicate',
  tree: 'opscenter.layout.refusal.tree',
};

function storage(key: string): Storage | null {
  try {
    const store = globalThis.localStorage;
    if (!store) return null;
    store.getItem(key);
    return store;
  } catch {
    return null;
  }
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

export function validate(
  raw: unknown,
  metas: MetaMap = META,
  page: LayoutPage = 'home',
  currentPrimarySessionId: string = '',
): Validation {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { layout: null, refusal: 'malformed', repaired: false };
  const replaced = replaceCells(raw, page);
  if (replaced.migrated) {
    const inner = validate(replaced.raw, metas, page, currentPrimarySessionId);
    return inner.layout ? { ...inner, migrated: true } : inner;
  }
  const dropped = dropRetiredCells(raw, page);
  if (dropped.migrated) {
    const inner = validate(dropped.raw, metas, page, currentPrimarySessionId);
    return inner.layout ? { ...inner, migrated: true } : inner;
  }
  const stored = readStoredGrid(raw, page, (id) => Object.hasOwn(metas, id) || isInstanceId(id as SlotId));
  if (stored.kind === 'v7-refused') return { layout: null, refusal: 'tree', repaired: false };
  if (stored.kind === 'v7') {
    const inner = validate(stored.grid, metas, page, currentPrimarySessionId);
    const lossy = stored.adaptation.outcome === 'adapted_lossy';
    return inner.layout && lossy ? { ...inner, repaired: true } : inner;
  }
  const blob = raw as Record<string, unknown>;
  if (blob['v'] !== SCHEMA_VERSION) return { layout: null, refusal: 'version', repaired: false };
  if (!Array.isArray(blob['rows']) || blob['rows'].length === 0) return { layout: null, refusal: 'rows', repaired: false };

  let repaired = false;
  const seenRows = new Set<string>();
  const seenCells = new Set<string>();
  let viewers = 0;
  const rows: RowModel[] = [];

  for (const entry of blob['rows'] as unknown[]) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return { layout: null, refusal: 'rows', repaired: false };
    const row = entry as Record<string, unknown>;
    const id = row['id'];
    if (typeof id !== 'string') return { layout: null, refusal: 'row-id', repaired: false };
    const kind = rowKind(page, id);
    if (!kind) return { layout: null, refusal: 'row-id', repaired: false };
    if (seenRows.has(id)) return { layout: null, refusal: 'row-id', repaired: false };
    seenRows.add(id);
    if (row['kind'] !== kind) return { layout: null, refusal: 'row-kind', repaired: false };
    if (!Array.isArray(row['slots'])) return { layout: null, refusal: 'rows', repaired: false };
    const reserved = readReserved(row['reserved']);
    if (!reserved) return { layout: null, refusal: 'spans', repaired: false };

    const slots: Slot[] = [];
    for (const held of row['slots'] as unknown[]) {
      if (!held || typeof held !== 'object' || Array.isArray(held)) return { layout: null, refusal: 'cells', repaired: false };
      const slot = held as Record<string, unknown>;
      const cell = slot['id'];
      const cellKind = slotKind(cell, metas);
      if (!cellKind || typeof cell !== 'string') return { layout: null, refusal: 'cells', repaired: false };
      if (seenCells.has(cell)) return { layout: null, refusal: 'cells', repaired: false };
      seenCells.add(cell);
      if (cellKind === 'instance' && isViewerSlot(cell)) viewers += 1;
      if (!positive(slot['fr'])) repaired = true;
      const span = slot['span'];
      if (span !== undefined) {
        if (typeof span !== 'number' || !Number.isFinite(span) || span < 1 || span > MAX_SPAN) {
          return { layout: null, refusal: 'spans', repaired: false };
        }
      }
      const made: Slot = { id: cell as SlotId, fr: positive(slot['fr']) ? slot['fr'] : 0 };
      if (typeof span === 'number' && span >= 2) made.span = Math.floor(span);
      slots.push(made);
    }

    const usable = slots.filter((slot) => slot.fr > 0);
    const fill = usable.length ? usable.reduce((sum, slot) => sum + slot.fr, 0) / usable.length : 1;
    const evened = slots.map((slot) => (slot.fr > 0 ? slot : { ...slot, fr: fill }));
    const fixed = normalizeRow({ id: id as RowId, kind, size: 0, slots: evened });
    if (fixed.slots.length !== slots.length) return { layout: null, refusal: 'cells', repaired: false };

    let size = typeof row['size'] === 'number' && Number.isFinite(row['size']) ? row['size'] : Number.NaN;
    if (kind === 'px') {
      const clamped = Number.isFinite(size) && size > 0 ? Math.min(size, ROW_MAX) : rowFloor(fixed, metas);
      if (clamped !== size) repaired = true;
      size = clamped;
    } else if (!positive(size)) {
      repaired = true;
      size = 0;
    }
    rows.push(reserved.length ? { ...fixed, size, reserved } : { ...fixed, size });
  }

  const hidden: SlotId[] = [];
  const rawHidden = blob['hidden'];
  if (!Array.isArray(rawHidden)) return { layout: null, refusal: 'cells', repaired: false };
  for (const id of rawHidden as unknown[]) {
    const kind = slotKind(id, metas);
    if (!kind || typeof id !== 'string') return { layout: null, refusal: 'cells', repaired: false };
    if (seenCells.has(id)) return { layout: null, refusal: 'cells', repaired: false };
    seenCells.add(id);
    if (kind === 'instance' && isViewerSlot(id)) viewers += 1;
    hidden.push(id as SlotId);
  }

  for (const slot of resetLayout(metas, page).rows.flatMap((one) => one.slots)) {
    if (isInstanceId(slot.id)) continue;
    if (!seenCells.has(slot.id)) return { layout: null, refusal: 'cells', repaired: false };
  }
  if (viewers > MAX_VIEWERS) return { layout: null, refusal: 'cells', repaired: false };

  const primaryId = (currentPrimarySessionId ?? '').trim();
  if (page === 'terminal' && primaryId) {
    const collision = `terminal:${primaryId}` as SlotId;
    if (collision !== PRIMARY_SLOT && seenCells.has(collision)) {
      return { layout: null, refusal: 'primary-duplicate', repaired: false };
    }
  }

  const collapsed: SlotId[] = [];
  const rawCollapsed = blob['collapsed'];
  if (!Array.isArray(rawCollapsed)) return { layout: null, refusal: 'cells', repaired: false };
  const seenCollapsed = new Set<string>();
  for (const id of rawCollapsed as unknown[]) {
    if (!slotKind(id, metas) || typeof id !== 'string') return { layout: null, refusal: 'cells', repaired: false };
    if (seenCollapsed.has(id)) return { layout: null, refusal: 'cells', repaired: false };
    seenCollapsed.add(id);
    collapsed.push(id as SlotId);
  }

  const headerOff: SlotId[] = [];
  const rawHeaderOff = blob['headerOff'];
  if (rawHeaderOff !== undefined) {
    const held = Array.isArray(rawHeaderOff) ? (rawHeaderOff as unknown[]) : [];
    for (const id of held) {
      if (typeof id === 'string' && slotKind(id, metas) && !headerOff.includes(id as SlotId)) headerOff.push(id as SlotId);
    }
    if (!Array.isArray(rawHeaderOff) || headerOff.length !== held.length) repaired = true;
  }

  const flex = rows.filter((row) => row.kind === 'flex');
  if (flex.length > 0) {
    if (flex.some((row) => !positive(row.size))) {
      repaired = true;
      for (const row of flex) row.size = 1 / flex.length;
    } else {
      const total = flex.reduce((sum, row) => sum + row.size, 0);
      if (Math.abs(total - 1) > 1e-9) {
        repaired = true;
        for (const row of flex) row.size = row.size / total;
      }
    }
  }

  const heroCollapsed = blob['heroCollapsed'] === true;
  const spanFixed = repairSpans({ v: SCHEMA_VERSION, rows, hidden, heroCollapsed, collapsed, ...(headerOff.length ? { headerOff } : {}) });
  const reconciled = foldSpanOnlyRows(spanFixed);
  if (reconciled.rows.length === 0) return { layout: null, refusal: 'rows', repaired: false };
  if (spanFixed.rows !== rows) repaired = true;
  return { layout: reconciled, refusal: null, repaired };
}

function refused(page: LayoutPage, notice: string, layout: Layout, session = ''): LoadResult {
  clear(page, session);
  return { layout, notice, stored: false };
}

/* gives the same there is nothing */
const PERMANENT_REFUSALS: ReadonlySet<Refusal> = new Set<Refusal>([
  'unreadable',
  'oversize',
  'malformed',
  'version',
  'rows',
  'row-id',
  'row-kind',
  'spans',
  'cells',
  'tree',
]);

export function load(
  metas: MetaMap = META,
  page: LayoutPage = 'home',
  currentPrimarySessionId: string = '',
  session = '',
): LoadResult {
  const key = storageKey(page, session);
  const fallback = (): Layout => resetLayout(metas, page);
  const store = storage(key);
  if (!store) {
    return { layout: fallback(), notice: t('opscenter.layout.not_saving'), stored: false };
  }
  let text: string | null = null;
  try {
    text = store.getItem(key);
  } catch {
    return { layout: fallback(), notice: t(NOTICE_KEYS.unreadable), stored: false };
  }
  if (text === null) return { layout: fallback(), notice: '', stored: false };
  if (text.length > MAX_BYTES) {
    return refused(page, t(NOTICE_KEYS.oversize), fallback(), session);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return refused(page, t(NOTICE_KEYS.malformed), fallback(), session);
  }
  const checked = validate(parsed, metas, page, currentPrimarySessionId);
  if (!checked.layout || checked.refusal) {
    const refusal = checked.refusal ?? 'malformed';
    if (refusal === 'absent') return { layout: fallback(), notice: '', stored: false };
    if (!PERMANENT_REFUSALS.has(refusal)) {
      return { layout: fallback(), notice: t(NOTICE_KEYS[refusal]), stored: false };
    }
    return refused(page, t(NOTICE_KEYS[refusal]), fallback(), session);
  }
  return {
    layout: checked.layout,
    notice: checked.repaired ? t('opscenter.layout.adjusted') : '',
    stored: true,
    ...(checked.migrated ? { migrated: true } : {}),
  };
}

const pending = new Map<string, Layout>();
let timer: ReturnType<typeof setTimeout> | undefined;
let frame = 0;

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

function announceOversizeSave(key: string): void {
  const id = `layout-oversize:${key}`;
  if (oversizeAnnounced.has(id)) return;
  oversizeAnnounced.add(id);
  const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
  surface?.add({
    id,
    session_id: null,
    kind: 'LayoutOversize',
    title: t('opscenter.layout.save_oversize.title'),
    body: t('opscenter.layout.save_oversize.body'),
    session_label: t('opscenter.layout.save_oversize.surface'),
    local: true,
  });
}

const oversizeAnnounced = new Set<string>();

export function flushSave(page?: LayoutPage, session = ''): void {
  if (timer !== undefined) {
    clearTimeout(timer);
    timer = undefined;
  }
  if (frame && typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(frame);
    frame = 0;
  }
  const keys = page ? [storageKey(page, session)] : [...pending.keys()];
  for (const key of keys) {
    const layout = pending.get(key);
    pending.delete(key);
    if (!layout) continue;
    const store = storage(key);
    if (!store) continue;
    try {
      const text = JSON.stringify(layout);
      if (text.length > MAX_BYTES) {
        console.warn('opscenter: a layout is over the size limit and was not saved', { key, bytes: text.length, limit: MAX_BYTES });
        announceOversizeSave(key);
        continue;
      }
      store.setItem(key, text);
      oversizeAnnounced.delete(`layout-oversize:${key}`);
    } catch {
    }
  }
  if (pending.size > 0) timer = setTimeout(flushSave, SAVE_DELAY);
}

let homeCacheWrites = true;

export function stopHomeCacheWrites(): void {
  homeCacheWrites = false;
}

export function save(layout: Layout, page: LayoutPage = 'home', session = ''): void {
  if (page === 'home' && !homeCacheWrites) return;
  pending.set(storageKey(page, session), layout);
  if (timer !== undefined) clearTimeout(timer);
  timer = setTimeout(flushSave, SAVE_DELAY);
  if (!frame && typeof requestAnimationFrame === 'function') {
    frame = requestAnimationFrame(() => {
      frame = 0;
    });
  }
}

export function clear(page: LayoutPage = 'home', session = ''): void {
  const key = storageKey(page, session);
  pending.delete(key);
  if (pending.size === 0 && timer !== undefined) {
    clearTimeout(timer);
    timer = undefined;
  }
  const store = storage(key);
  if (!store) return;
  try {
    store.removeItem(key);
  } catch {
  }
}

export function installFlushOnExit(): () => void {
  const onHide = (): void => flushSave();
  const onVisibility = (): void => {
    if (document.visibilityState === 'hidden') flushSave();
  };
  window.addEventListener('pagehide', onHide);
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    window.removeEventListener('pagehide', onHide);
    document.removeEventListener('visibilitychange', onVisibility);
  };
}
