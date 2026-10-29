
import { META } from './meta';
import { MAX_SPAN, placeOf, repairSpans, spanOf } from './spans';
import { CELL_SQUEEZE_MIN, computeTracks } from './tracks';
import type { Layout, MetaMap, SlotId } from './types';

export type SpanRefusal = null | 'not-placed' | 'last-row' | 'no-room' | 'max';

interface SpanPlan {
  refusal: SpanRefusal;
  next: Layout | null;
}

function planSpanDown(
  layout: Layout,
  id: SlotId,
  widthPx: number,
  gutter: number,
  metas: MetaMap,
): SpanPlan {
  const place = placeOf(layout, id);
  if (!place) return { refusal: 'not-placed', next: null };
  const slot = layout.rows[place.rowAt]?.slots[place.slotAt];
  if (!slot) return { refusal: 'not-placed', next: null };
  const reach = spanOf(slot);
  if (reach >= MAX_SPAN) return { refusal: 'max', next: null };
  const underAt = place.rowAt + reach;
  const under = layout.rows[underAt];
  if (!under) return { refusal: 'last-row', next: null };

  const before = computeTracks({ rows: layout.rows, width: widthPx, height: 0, gutter, metas });
  const mine = before.rows[place.rowAt]?.cells.find((cell) => cell.slotId === id);
  if (!mine) return { refusal: 'not-placed', next: null };

  const drawn = before.rows[underAt]?.cells ?? [];
  const centre = mine.x + mine.width / 2;
  let at = 0;
  for (const one of under.slots) {
    const box = drawn.find((cell) => cell.slotId === one.id);
    if (box && box.x + box.width / 2 < centre) at += 1;
  }
  const leftRoom = mine.x - gutter;
  const rightRoom = Math.floor(widthPx) - (mine.x + mine.width) - gutter;
  if (leftRoom <= 0) at = 0;
  else if (rightRoom <= 0) at = under.slots.length;

  const rows = layout.rows.map((row, index) => {
    if (index === place.rowAt) {
      return {
        ...row,
        slots: row.slots.map((one) => (one.id === id ? { ...one, span: reach + 1 } : one)),
      };
    }
    if (index !== underAt) return row;
    return { ...row, reserved: [...(row.reserved ?? []).filter((one) => one.of !== id), { of: id, at }] };
  });
  const next = repairSpans({ ...layout, rows });

  const after = computeTracks({ rows: next.rows, width: widthPx, height: 0, gutter, metas });
  for (let step = 1; step <= reach; step += 1) {
    for (const cell of after.rows[place.rowAt + step]?.cells ?? []) {
      if (cell.slotId === null || cell.width >= CELL_SQUEEZE_MIN) continue;
      const was = before.rows[place.rowAt + step]?.cells.find((one) => one.slotId === cell.slotId);
      if (!was || cell.width < was.width) return { refusal: 'no-room', next: null };
    }
  }
  return { refusal: null, next };
}

export function canSpanDown(
  layout: Layout,
  id: SlotId,
  widthPx: number,
  gutter: number,
  metas: MetaMap = META,
): SpanRefusal {
  return planSpanDown(layout, id, widthPx, gutter, metas).refusal;
}

export function spanDown(
  layout: Layout,
  id: SlotId,
  widthPx: number,
  gutter: number,
  metas: MetaMap = META,
): Layout {
  return planSpanDown(layout, id, widthPx, gutter, metas).next ?? layout;
}
