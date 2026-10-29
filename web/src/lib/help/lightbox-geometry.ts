
export interface LightboxRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Viewport {
  w: number;
  h: number;
}

export const MIN_W = 240;
export const MIN_H = 160;
export const KEY_STEP = 20;
export const EDGE_GAP = 12;
export const STORAGE_KEY = 'carnivore.media_lightbox.rect';

export function clampRect(rect: LightboxRect, vp: Viewport): LightboxRect {
  const w = Math.round(Math.min(Math.max(rect.w, Math.min(MIN_W, vp.w)), vp.w));
  const h = Math.round(Math.min(Math.max(rect.h, Math.min(MIN_H, vp.h)), vp.h));
  const x = Math.round(Math.min(Math.max(rect.x, 0), vp.w - w));
  const y = Math.round(Math.min(Math.max(rect.y, 0), vp.h - h));
  return { x, y, w, h };
}

export function defaultRect(vp: Viewport): LightboxRect {
  const w = Math.min(vp.w - 2 * EDGE_GAP, Math.max(MIN_W, Math.round(vp.w * 0.7)));
  const h = Math.min(vp.h - 2 * EDGE_GAP, Math.max(MIN_H, Math.round(vp.h * 0.75)));
  return clampRect({ x: Math.round((vp.w - w) / 2), y: Math.round((vp.h - h) / 2), w, h }, vp);
}

export function stepRect(rect: LightboxRect, key: string, shift: boolean, vp: Viewport): LightboxRect | null {
  const dx = key === 'ArrowLeft' ? -KEY_STEP : key === 'ArrowRight' ? KEY_STEP : 0;
  const dy = key === 'ArrowUp' ? -KEY_STEP : key === 'ArrowDown' ? KEY_STEP : 0;
  if (!dx && !dy) return null;
  return clampRect(shift ? { ...rect, w: rect.w + dx, h: rect.h + dy } : { ...rect, x: rect.x + dx, y: rect.y + dy }, vp);
}

export function loadRect(): LightboxRect | null {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Partial<LightboxRect> | null;
    if (!raw) return null;
    const { x, y, w, h } = raw;
    if (![x, y, w, h].every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
    return { x: x as number, y: y as number, w: w as number, h: h as number };
  } catch {
    return null;
  }
}

export function saveRect(rect: LightboxRect): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rect));
  } catch {
  }
}
