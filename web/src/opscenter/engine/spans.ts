
import type { Layout, Reservation, RowModel, Slot, SlotId } from './types';

export const MAX_SPAN = 64;

export type VisualCell =
  | { kind: 'slot'; slot: Slot; index: number }
  | { kind: 'reserved'; of: SlotId };

export function spanOf(slot: Slot): number {
  const span = slot.span;
  if (typeof span !== 'number' || !Number.isFinite(span)) return 1;
  return Math.max(1, Math.min(Math.floor(span), MAX_SPAN));
}

function reservedAt(at: number, count: number): number {
  if (!Number.isFinite(at)) return count;
  return Math.max(0, Math.min(Math.round(at), count));
}

export function visualOrder(row: RowModel): VisualCell[] {
  const held = row.reserved ?? [];
  if (held.length === 0) {
    return row.slots.map((slot, index) => ({ kind: 'slot', slot, index }) as VisualCell);
  }
  const count = row.slots.length;
  const marks = held.map((one) => ({ of: one.of, at: reservedAt(one.at, count) }));
  const out: VisualCell[] = [];
  for (let index = 0; index <= count; index += 1) {
    for (const mark of marks) {
      if (mark.at === index) out.push({ kind: 'reserved', of: mark.of });
    }
    const slot = row.slots[index];
    if (slot) out.push({ kind: 'slot', slot, index });
  }
  return out;
}

export function placeOf(layout: Layout, id: SlotId): { rowAt: number; slotAt: number } | null {
  for (let rowAt = 0; rowAt < layout.rows.length; rowAt += 1) {
    const slots = layout.rows[rowAt]?.slots ?? [];
    for (let slotAt = 0; slotAt < slots.length; slotAt += 1) {
      if (slots[slotAt]?.id === id) return { rowAt, slotAt };
    }
  }
  return null;
}

function sameShape(a: readonly RowModel[], b: readonly RowModel[]): boolean {
  if (a.length !== b.length) return false;
  for (let index = 0; index < a.length; index += 1) {
    const left = a[index];
    const right = b[index];
    if (!left || !right || left.id !== right.id) return false;
    if (left.slots.length !== right.slots.length) return false;
    for (let at = 0; at < left.slots.length; at += 1) {
      const one = left.slots[at];
      const other = right.slots[at];
      if (!one || !other || one.id !== other.id || spanOf(one) !== spanOf(other)) return false;
    }
    const held = left.reserved ?? [];
    const theirs = right.reserved ?? [];
    if (held.length !== theirs.length) return false;
    for (let at = 0; at < held.length; at += 1) {
      if (held[at]?.of !== theirs[at]?.of || held[at]?.at !== theirs[at]?.at) return false;
    }
  }
  return true;
}

function onePass(rows: readonly RowModel[]): RowModel[] {
  const owed = new Map<number, Reservation[]>();
  const spans = new Map<SlotId, number>();

  for (let rowAt = 0; rowAt < rows.length; rowAt += 1) {
    const row = rows[rowAt];
    if (!row) continue;
    for (let slotAt = 0; slotAt < row.slots.length; slotAt += 1) {
      const slot = row.slots[slotAt];
      if (!slot) continue;
      const reach = Math.min(spanOf(slot), rows.length - rowAt);
      spans.set(slot.id, reach);
      if (reach < 2) continue;
      for (let step = 1; step < reach; step += 1) {
        const target = rows[rowAt + step];
        if (!target) continue;
        const kept = (target.reserved ?? []).find((one) => one.of === slot.id);
        const at = reservedAt(kept ? kept.at : slotAt, target.slots.length);
        const list = owed.get(rowAt + step) ?? [];
        list.push({ of: slot.id, at });
        owed.set(rowAt + step, list);
      }
    }
  }

  const out: RowModel[] = [];
  for (let rowAt = 0; rowAt < rows.length; rowAt += 1) {
    const row = rows[rowAt];
    if (!row) continue;
    const reserved = (owed.get(rowAt) ?? []).slice().sort((a, b) => a.at - b.at);
    if (row.slots.length === 0 && reserved.length === 0) continue;
    const slots = row.slots.map((slot) => {
      const reach = spans.get(slot.id) ?? 1;
      if (reach >= 2) return spanOf(slot) === reach ? slot : { ...slot, span: reach };
      if (slot.span === undefined) return slot;
      const { span: _dropped, ...rest } = slot;
      return rest;
    });
    if (reserved.length === 0) {
      if (row.reserved === undefined) out.push({ ...row, slots });
      else {
        const { reserved: _gone, ...rest } = row;
        out.push({ ...rest, slots });
      }
      continue;
    }
    out.push({ ...row, slots, reserved });
  }
  return out;
}

function trimTail(rows: readonly RowModel[]): readonly RowModel[] {
  let last = rows.length - 1;
  while (last >= 0 && rows[last]!.slots.length === 0) last -= 1;
  if (last < 0 || last === rows.length - 1) return rows;
  const home = rows[last]!;
  const reachesTail = (slot: Slot): boolean => spanOf(slot) >= rows.length - last;
  if (home.slots.every(reachesTail)) return rows;
  const tail = rows.slice(last + 1);
  const gift = tail.filter((row) => row.kind === home.kind).reduce((sum, row) => sum + row.size, 0);
  return [...rows.slice(0, last), { ...home, size: home.size + gift }];
}

export function repairSpans(layout: Layout): Layout {
  let rows: readonly RowModel[] = layout.rows;
  for (let pass = 0; pass < 4; pass += 1) {
    const next = trimTail(onePass(rows));
    if (sameShape(next, rows)) {
      return rows === layout.rows ? layout : { ...layout, rows: rows as RowModel[] };
    }
    rows = next;
  }
  return { ...layout, rows: rows as RowModel[] };
}

function withSpan(layout: Layout, id: SlotId, span: number): Layout {
  const rows = layout.rows.map((row) => {
    if (!row.slots.some((slot) => slot.id === id)) return row;
    return {
      ...row,
      slots: row.slots.map((slot) => {
        if (slot.id !== id) return slot;
        if (span >= 2) return { ...slot, span };
        const { span: _dropped, ...rest } = slot;
        return rest;
      }),
    };
  });
  return repairSpans({ ...layout, rows });
}

export function spanUp(layout: Layout, id: SlotId): Layout {
  const place = placeOf(layout, id);
  if (!place) return layout;
  const slot = layout.rows[place.rowAt]?.slots[place.slotAt];
  if (!slot) return layout;
  const now = spanOf(slot);
  if (now < 2) return layout;
  return withSpan(layout, id, now - 1);
}

export function clearSpan(layout: Layout, id: SlotId): Layout {
  const place = placeOf(layout, id);
  if (!place) return layout;
  const slot = layout.rows[place.rowAt]?.slots[place.slotAt];
  if (!slot || spanOf(slot) < 2) return layout;
  return withSpan(layout, id, 1);
}

