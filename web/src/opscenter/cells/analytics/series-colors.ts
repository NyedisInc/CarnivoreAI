
export const SERIES_COUNT = 8;

export interface ColorContext {
  fillStyle: string | CanvasGradient | CanvasPattern;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  getImageData(x: number, y: number, w: number, h: number): { data: ArrayLike<number> };
}

export interface SeriesLook { color: string; dashed: boolean }

const SENTINEL = '#010203';
const cache = new Map<string, string>();

export function toSrgb(css: string, ctx: ColorContext, fallback: string): string {
  const hit = cache.get(css);
  if (hit) return hit;
  ctx.fillStyle = SENTINEL;
  ctx.fillStyle = css;
  if (ctx.fillStyle === SENTINEL && css.replace(/\s/g, '').toLowerCase() !== SENTINEL) return fallback;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillRect(0, 0, 1, 1);
  const px = ctx.getImageData(0, 0, 1, 1).data;
  const [r, g, b, a] = [px[0], px[1], px[2], px[3]] as [number, number, number, number];
  const out = a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${Math.round(a / 255 * 100) / 100})`;
  if (cache.size > 128) cache.clear();
  cache.set(css, out);
  return out;
}

export function clearColorCache(): void { cache.clear(); }

export function seriesLook(index: number, palette: string[]): SeriesLook {
  return { color: palette[index % palette.length] as string, dashed: index >= SERIES_COUNT };
}

export function assignSeriesLooks(keys: string[], palette: string[]): Map<string, SeriesLook> {
  const looks = new Map<string, SeriesLook>();
  for (const key of keys) if (!looks.has(key)) looks.set(key, seriesLook(looks.size, palette));
  return looks;
}

export function mergeLegendSelection(previous: Record<string, boolean>, names: string[]): Record<string, boolean> {
  const merged: Record<string, boolean> = {};
  for (const name of names) merged[name] = previous[name] !== false;
  return merged;
}
