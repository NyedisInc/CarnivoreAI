
import { META } from './meta';
import { freeRowId, normalizeRow, rowHeightFor, rowOfCell, withoutCell } from './model';
import { MAX_SPAN, clearSpan, placeOf, repairSpans, spanOf, visualOrder } from './spans';
import type { Layout, MetaMap, Reservation, RowModel, Slot, SlotId } from './types';

export type StackEdge = 'above' | 'below';

function evenFlex(rows: RowModel[]): RowModel[] {
  const total = rows.reduce((sum, row) => (row.kind === 'flex' ? sum + row.size : sum), 0);
  if (total <= 0 || Math.abs(total - 1) < 1e-9) return rows;
  return rows.map((row) => (row.kind === 'flex' ? { ...row, size: row.size / total } : row));
}

export function stackCell(
  layout: Layout,
  id: SlotId,
  of: SlotId,
  edge: StackEdge,
  metas: MetaMap = META,
): Layout {
  if (id === of) return layout;
  const lifted = clearSpan(layout, id);
  const from = rowOfCell(lifted, id);
  if (!from) return layout;
  const base = repairSpans({
    ...lifted,
    rows: evenFlex(lifted.rows.map((row) => (row.id === from.id ? normalizeRow(withoutCell(row, id)) : row))),
  });

  const place = placeOf(base, of);
  if (!place) return layout;
  const target = base.rows[place.rowAt]?.slots[place.slotAt];
  if (!target) return layout;
  const refAt = edge === 'below' ? place.rowAt + spanOf(target) - 1 : place.rowAt;
  const ref = base.rows[refAt];
  if (!ref) return layout;

  const grown = new Map<SlotId, number>();
  const spanById = new Map<SlotId, number>();
  for (const row of base.rows) for (const slot of row.slots) spanById.set(slot.id, spanOf(slot));

  const minted: Slot[] = [];
  const mintedHeld: Reservation[] = [];
  const refHeld: Reservation[] = [];
  let passed = false;
  for (const entry of visualOrder(ref)) {
    const cell = entry.kind === 'slot' ? entry.slot.id : entry.of;
    if (cell === of) {
      minted.push({ id, fr: edge === 'above' && entry.kind === 'slot' ? entry.slot.fr : 1 });
      passed = true;
      continue;
    }
    const next = (spanById.get(cell) ?? 1) + 1;
    if (next > MAX_SPAN) return layout;
    grown.set(cell, next);
    if (edge === 'above') {
      refHeld.push({ of: cell, at: passed ? 1 : 0 });
      if (entry.kind === 'slot') minted.push({ ...entry.slot, span: next });
      else mintedHeld.push({ of: cell, at: minted.length });
    } else {
      mintedHeld.push({ of: cell, at: minted.length });
    }
  }

  const flex = ref.kind === 'flex';
  const splitSize = flex ? ref.size / 2 : ref.size;
  const newRow: RowModel = normalizeRow({
    id: freeRowId(base),
    kind: ref.kind,
    size: flex ? splitSize : rowHeightFor(minted.map((slot) => slot.id), metas),
    slots: minted,
    ...(mintedHeld.length ? { reserved: mintedHeld } : {}),
  });

  const rows: RowModel[] = [];
  base.rows.forEach((row, at) => {
    let next: RowModel = {
      ...row,
      slots: row.slots.map((slot) => {
        const span = grown.get(slot.id);
        return span === undefined ? slot : { ...slot, span };
      }),
    };
    if (at === refAt) {
      if (edge === 'above') {
        const kept = row.slots.find((slot) => slot.id === of);
        const { reserved: _dropped, ...rest } = row;
        next = { ...rest, slots: kept ? [{ ...kept, fr: 1 }] : [] };
        if (refHeld.length) next.reserved = refHeld;
      }
      if (flex) next = { ...next, size: splitSize };
      if (edge === 'above') rows.push(newRow);
      rows.push(next);
      if (edge === 'below') rows.push(newRow);
      return;
    }
    rows.push(next);
  });
  return repairSpans({ ...base, rows: evenFlex(rows) });
}
