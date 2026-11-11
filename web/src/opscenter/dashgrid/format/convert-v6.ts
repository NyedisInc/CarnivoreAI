
import { pack } from '../../../lib/motion-grid/pack';
import { META } from '../../engine/meta';
import { sharePixels, computeTracks, GUTTER } from '../../engine/tracks';
import type { MetaMap, RowModel, SlotId } from '../../engine/types';
import { MAX_H, type GridItem } from './grid-format';

const COLS = 24;
const PITCH = 40;
export const NOMINAL_WIDTH = 1440;

interface Track {
  id: SlotId | null;
  weight: number;
  height: number;
}

function columnWidths(weights: readonly number[]): number[] {
  const out = sharePixels(weights, COLS);
  for (let at = out.indexOf(0); at >= 0; at = out.indexOf(0)) {
    const big = out.indexOf(Math.max(...out));
    out[big] = (out[big] ?? 0) - 1;
    out[at] = 1;
  }
  return out;
}

export function convertV6(layout: { rows: readonly RowModel[] }, metas: MetaMap = META): GridItem[] {
  const surface = computeTracks({ rows: layout.rows, width: NOMINAL_WIDTH, height: 0, gutter: GUTTER, metas });
  const items: GridItem[] = [];
  for (const row of surface.rows) {
    const tracks: Track[] = row.cells.map((c) => ({
      id: c.slotId,
      weight: c.width + GUTTER,
      height: c.slotId !== null && c.span >= 2 ? (surface.spanHeight.get(c.slotId) ?? row.height) : row.height,
    }));
    const real = tracks.filter((t) => t.id !== null);
    const groups = tracks.length <= COLS ? [tracks] : Array.from({ length: Math.ceil(real.length / COLS) }, (_, k) => real.slice(k * COLS, (k + 1) * COLS));
    const y = Math.round(row.top / PITCH);
    for (const group of groups) {
      const widths = columnWidths(group.map((t) => t.weight));
      let x = 0;
      group.forEach((t, k) => {
        const w = widths[k] ?? 1;
        if (t.id !== null) {
          items.push({ id: t.id, x, y, w, h: Math.min(MAX_H, Math.max(1, Math.round((row.top + t.height) / PITCH) - y)) });
        }
        x += w;
      });
    }
  }
  return pack(items, COLS, null) as GridItem[];
}
