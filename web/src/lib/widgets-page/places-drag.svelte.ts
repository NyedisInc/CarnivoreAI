/* the widgets page */
import type { PlaceId } from './places';

export interface DragState {
    widget: string | null;
    row: { place: PlaceId; key: string } | null;
    ins: { key: string; pos: 'before' | 'after' } | null;
}

export const drag: DragState = $state({ widget: null, row: null, ins: null });

export function endDrag(): void {
    drag.widget = null;
    drag.row = null;
    drag.ins = null;
}
