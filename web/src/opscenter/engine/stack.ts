
import { foldLifted } from './compact';
import { META } from './meta';
import { freeRowId, liftedRows, normalizeRow, rowHeightFor, rowOfCell } from './model';
import { NOMINAL_HEIGHT, cutAtMidpoint, keepRowPx } from './stack-mid';
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
  of: SlotId | readonly SlotId[],
  edge: StackEdge,
  metas: MetaMap = META,
  width?: number,
  height?: number,
): Layout {
  const run: readonly SlotId[] = typeof of === 'string' ? [of] : of;
  if (run.length === 0 || run.includes(id) || (run.length > 1 && edge === 'above')) return layout;
  const lifted = clearSpan(layout, id);
  const from = rowOfCell(lifted, id);
  if (!from) return layout;
  const base = foldLifted(
    layout,
    repairSpans({
      ...lifted,
      rows: evenFlex(liftedRows(layout, id, width, true, height)),
    }),
    id,
    metas,
    width,
    height,
  );

  if (run.length === 1) {
    const cut = cutAtMidpoint(base, id, run[0]!, edge, width, height);
    if (cut === 'refused') return layout;
    if (cut) return repairSpans({ ...cut, rows: evenFlex(cut.rows) });
  }

  const refRows = run.map((cell) => {
    const place = placeOf(base, cell);
    const slot = place ? base.rows[place.rowAt]?.slots[place.slotAt] : undefined;
    return place && slot ? (edge === 'below' ? place.rowAt + spanOf(slot) - 1 : place.rowAt) : -1;
  });
  const refAt = refRows[0] ?? -1;
  if (refRows.some((at) => at !== refAt)) return layout;
  const ref = base.rows[refAt];
  const of0 = run[0]!;
  if (!ref) return layout;
  const ofSet = new Set<SlotId>(run);
  const drawnRun = visualOrder(ref).flatMap((entry, at) => (ofSet.has(entry.kind === 'slot' ? entry.slot.id : entry.of) ? [at] : []));
  if (drawnRun.length !== run.length || drawnRun.some((at, step) => at !== (drawnRun[0] ?? 0) + step)) return layout;

  const grown = new Map<SlotId, number>();
  const spanById = new Map<SlotId, number>();
  for (const row of base.rows) for (const slot of row.slots) spanById.set(slot.id, spanOf(slot));

  const minted: Slot[] = [];
  const mintedHeld: Reservation[] = [];
  const refHeld: Reservation[] = [];
  let passed = false;
  for (const entry of visualOrder(ref)) {
    const cell = entry.kind === 'slot' ? entry.slot.id : entry.of;
    if (ofSet.has(cell)) {
      if (!passed) minted.push({ id, fr: edge === 'above' && entry.kind === 'slot' ? entry.slot.fr : 1 });
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
        const kept = row.slots.find((slot) => slot.id === of0);
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
  return repairSpans({ ...base, rows: evenFlex(flex ? keepRowPx(rows, refAt, height ?? NOMINAL_HEIGHT) : rows) });
}
