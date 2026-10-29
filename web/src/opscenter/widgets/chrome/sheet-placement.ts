
export const SHEET_WIDTH = 260;

export const SHEET_GAP = 8;

export const EDGE = 8;

export const OVERLAY_TOP = 26;

export const MIN_SHEET_HEIGHT = 120;

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface SheetPlacement {
  mode: 'right' | 'left' | 'overlay';
  left: number;
  top: number;
  width: number;
  height: number;
}

export function sheetPlacement(widget: Rect, view: { width: number; height: number }, sheetHeight = 0): SheetPlacement {
  const tall = Math.max(MIN_SHEET_HEIGHT, sheetHeight);
  const top = Math.max(EDGE, Math.min(widget.top, view.height - EDGE - tall));
  const right = widget.left + widget.width + SHEET_GAP;
  if (right + SHEET_WIDTH <= view.width - EDGE) {
    return { mode: 'right', left: right, top, width: SHEET_WIDTH, height: 0 };
  }
  const left = widget.left - SHEET_GAP - SHEET_WIDTH;
  if (left >= EDGE) return { mode: 'left', left, top, width: SHEET_WIDTH, height: 0 };
  return {
    mode: 'overlay',
    left: widget.left,
    top: widget.top + OVERLAY_TOP,
    width: widget.width,
    height: Math.max(0, widget.height - OVERLAY_TOP),
  };
}
