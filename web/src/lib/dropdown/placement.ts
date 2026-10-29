
export interface FieldBox { top: number; bottom: number; left: number; width: number }

export interface Placement { style: string; sheet: boolean; room: number }

export const SHEET_MAX_WIDTH = 767;

export function placePanel(box: FieldBox, view: { width: number; height: number }, sheet: boolean, widthFor: (boxWidth: number) => number): Placement {
    const below = view.height - box.bottom - 8;
    const above = box.top - 8;
    const up = below < 240 && above > below;
    const room = Math.max(160, Math.min(400, up ? above : below));
    const vertical = up ? `bottom:${view.height - box.top + 4}px;` : `top:${box.bottom + 4}px;`;
    if (sheet) return { style: `${vertical}left:0;right:0;max-height:${room}px;`, sheet, room };
    const width = widthFor(box.width);
    const left = Math.max(8, Math.min(box.left, view.width - width - 8));
    return { style: `${vertical}left:${left}px;width:${width}px;max-height:${room}px;`, sheet, room };
}

export function isSheetWidth(): boolean {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(`(max-width: ${SHEET_MAX_WIDTH}px)`).matches;
}
