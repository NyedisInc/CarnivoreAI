
import { SIZE_UNIT_PX, suggestedSizes } from '../widgets/fits';
import type { NamedFitSize } from '../widgets/named-sizes';
import type { FitSize, WidgetFits } from '../widgets/types';
import { rowOfCell, setRowHeight } from './model';
import { META } from './meta';
import type { Layout, MetaMap, SlotId } from './types';

const SHARE_MIN = 0.06;
const SHARE_MAX = 0.94;

export type SizeRefusal = 'alone' | 'flex-row' | 'not-placed' | null;

export function sizePresets(fits: WidgetFits | null): NamedFitSize[] {
  return fits ? suggestedSizes(fits) : [];
}

export function sizeRefusal(layout: Layout, id: SlotId): SizeRefusal {
  const row = rowOfCell(layout, id);
  if (!row) return 'not-placed';
  if (row.kind !== 'px') return 'flex-row';
  if (row.slots.length < 2) return 'alone';
  return null;
}

export function setCellSize(layout: Layout, id: SlotId, size: FitSize, freePx: number, metas: MetaMap = META): Layout {
  if (sizeRefusal(layout, id) !== null || freePx <= 0) return layout;
  const row = rowOfCell(layout, id);
  const self = row?.slots.find((slot) => slot.id === id);
  if (!row || !self) return layout;
  const share = Math.min(SHARE_MAX, Math.max(SHARE_MIN, (size.w * SIZE_UNIT_PX.w) / freePx));
  const others = row.slots.filter((slot) => slot.id !== id);
  const rest = others.reduce((sum, slot) => sum + slot.fr, 0);
  const slots = row.slots.map((slot) =>
    slot.id === id ? { ...slot, fr: share } : { ...slot, fr: rest > 0 ? (slot.fr / rest) * (1 - share) : (1 - share) / others.length },
  );
  const widened: Layout = { ...layout, rows: layout.rows.map((one) => (one.id === row.id ? { ...row, slots } : one)) };
  return setRowHeight(widened, row.id, size.h * SIZE_UNIT_PX.h, metas);
}
