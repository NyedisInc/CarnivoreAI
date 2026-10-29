
export const RANK_ROW_PX = 32;
export const RANK_BARE_ROW_PX = 20;
export const RANK_PAD_PX = 14;

export function rankedRowPlan(roomPx: number, have: number, max: number): { count: number; bars: boolean } {
  const most = Math.min(have, max);
  if (roomPx <= 0) return { count: most, bars: true };
  const free = roomPx - RANK_PAD_PX;
  if (free >= 2 * RANK_ROW_PX) return { count: Math.min(most, Math.floor(free / RANK_ROW_PX)), bars: true };
  return { count: Math.min(most, Math.max(0, Math.floor(free / RANK_BARE_ROW_PX))), bars: false };
}

export function wholeRowCount(roomPx: number, bottoms: readonly number[]): number {
  const at = bottoms.findIndex((bottom) => bottom > roomPx + ROW_EDGE_SLACK_PX);
  return at === -1 ? bottoms.length : at;
}

const ROW_EDGE_SLACK_PX = 0.5;
