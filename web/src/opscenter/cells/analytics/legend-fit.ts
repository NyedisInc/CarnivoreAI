
export const LEGEND_PAGER_PX = 66;
export const LEGEND_ICON_GAP_PX = 5;
export const LEGEND_MIN_TEXT_PX = 24;

export function legendTextWidth(canvasPx: number, left: number, right: number, iconPx: number): number {
  return Math.max(LEGEND_MIN_TEXT_PX, Math.floor(canvasPx - left - right - LEGEND_PAGER_PX - iconPx - LEGEND_ICON_GAP_PX));
}
