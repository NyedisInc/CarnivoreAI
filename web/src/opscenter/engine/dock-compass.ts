import type { Dragged, Rect, SnapWindow } from './drop-grammar';

export type CompassDir = 'centre' | 'up' | 'down' | 'left' | 'right';

export interface CompassSlot {
  dir: CompassDir;
  rect: Rect;
  allowed: boolean;
}

export interface CompassGeometry {
  window: string;
  plate: Rect;
  slots: CompassSlot[];
}

export const ICON_MAX_PX = 40;
export const ICON_MIN_PX = 18;
const GAP_PX = 4;
const PAD_PX = 6;

export function bodyOf(w: SnapWindow): Rect {
  const top = w.strip ? w.strip.y + w.strip.h : w.y;
  return { x: w.x, y: top, w: w.w, h: w.y + w.h - top };
}

export function compassGeometry(w: SnapWindow, dragged: Dragged): CompassGeometry | null {
  const own = dragged.kind === 'tab' && w.tabs.includes(dragged.tab);
  const splits = !own || w.tabs.length > 1;
  const centre = w.takesTabs && !own;
  if (!splits && !centre) return null;
  const body = bodyOf(w);
  const room = Math.min(body.w, body.h) - 2 * PAD_PX - 2 * GAP_PX;
  const size = Math.max(ICON_MIN_PX, Math.min(ICON_MAX_PX, Math.floor(room / 3)));
  const span = 3 * size + 2 * GAP_PX;
  const cx = body.x + body.w / 2;
  const cy = body.y + body.h / 2;
  const at = (col: number, row: number): Rect => ({
    x: cx - span / 2 + col * (size + GAP_PX),
    y: cy - span / 2 + row * (size + GAP_PX),
    w: size,
    h: size,
  });
  return {
    window: w.id,
    plate: { x: cx - span / 2 - PAD_PX, y: cy - span / 2 - PAD_PX, w: span + 2 * PAD_PX, h: span + 2 * PAD_PX },
    slots: [
      { dir: 'centre', rect: at(1, 1), allowed: centre },
      { dir: 'up', rect: at(1, 0), allowed: splits },
      { dir: 'down', rect: at(1, 2), allowed: splits },
      { dir: 'left', rect: at(0, 1), allowed: splits },
      { dir: 'right', rect: at(2, 1), allowed: splits },
    ],
  };
}

export interface CompassView {
  window: string;
  plate: Rect;
  icons: { dir: CompassDir; rect: Rect; enabled: boolean; hot: boolean }[];
}
