
export const VALUE_TICK_PX = 28;
export const TIME_LABEL_PX = 80;
const MIN_TICKS = 2;
const MAX_VALUE_TICKS = 6;
const MAX_TIME_LABELS = 8;

export function valueTickCount(plotPx: number): number {
  return Math.max(MIN_TICKS, Math.min(MAX_VALUE_TICKS, Math.floor(Math.max(0, plotPx) / VALUE_TICK_PX)));
}

export function timeLabelCount(plotPx: number): number {
  return Math.max(MIN_TICKS, Math.min(MAX_TIME_LABELS, Math.floor(Math.max(0, plotPx) / TIME_LABEL_PX)));
}

export interface PlotInsets { top: number; bottom: number; left: number; right: number }

export function axisCounts(box: { width: number; height: number }, insets: PlotInsets): { value: number; time: number } {
  return {
    value: valueTickCount(box.height - insets.top - insets.bottom),
    time: timeLabelCount(box.width - insets.left - insets.right),
  };
}
