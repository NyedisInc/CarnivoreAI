
export type Ground = 'dark' | 'light';

export interface Lch {
  l: number;
  c: number;
  h: number;
}

export const LIGHT_GROUND_MIN_L = 0.6;

export const BANDS: Readonly<Record<Ground, { minL: number; maxL: number }>> = {
  dark: { minL: 0.62, maxL: 0.92 },
  light: { minL: 0.5, maxL: 0.74 },
};

export const PALETTE_MIN_CHROMA = 0.12;
export const RELATIVE_CHROMA = 0.85;
export const BASE_GAMUT_ROOM = 0.15;
export const BASE_LIGHTNESS_ROOM = 0.1;
export const SHADE_RELATIVE_CHROMA = 0.5;
export const HUE_STEP = 5;
const STEP = 0.02;

const MUD: readonly (readonly [number, number])[] = [
  [0, 0.45], [35, 0.5], [50, 0.66], [65, 0.74], [80, 0.8], [110, 0.82], [125, 0.78], [140, 0.62], [155, 0.5], [360, 0.45],
];

export function mudFloor(h: number): number {
  const hue = ((h % 360) + 360) % 360;
  for (let i = 1; i < MUD.length; i++) {
    const [h1, l1] = MUD[i]!;
    const [h0, l0] = MUD[i - 1]!;
    if (hue <= h1) return Math.round((l0 + ((l1 - l0) * (hue - h0)) / (h1 - h0)) * 1000) / 1000;
  }
  return MUD[MUD.length - 1]![1];
}

export function oklab(p: Lch): [number, number, number] {
  const r = (p.h * Math.PI) / 180;
  return [p.l, p.c * Math.cos(r), p.c * Math.sin(r)];
}

const labs = new WeakMap<Lch, readonly [number, number, number]>();
const labOf = (p: Lch): readonly [number, number, number] => {
  let v = labs.get(p);
  if (!v) {
    v = oklab(p);
    labs.set(p, v);
  }
  return v;
};

export function deltaE(a: Lch, b: Lch): number {
  const [l1, a1, b1] = labOf(a);
  const [l2, a2, b2] = labOf(b);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

export function linearSrgb([L, a, b]: readonly [number, number, number]): [number, number, number] {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}

export function fromLinearSrgb([r, g, b]: readonly [number, number, number]): [number, number, number] {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

export function linearChannel(v: number): number {
  const c = v / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function srgbLightness(r: number, g: number, b: number): number {
  return fromLinearSrgb([linearChannel(r), linearChannel(g), linearChannel(b)])[0];
}

export function inGamut(p: Lch): boolean {
  return linearSrgb(oklab(p)).every((v) => v >= -1e-6 && v <= 1 + 1e-6);
}

export function maxChroma(l: number, h: number): number {
  let lo = 0;
  let hi = 0.5;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    if (inGamut({ l, c: mid, h })) lo = mid;
    else hi = mid;
  }
  return lo;
}

export function vibrant(p: Lch, relative = RELATIVE_CHROMA): boolean {
  if (p.c < PALETTE_MIN_CHROMA - 1e-9 || p.l < mudFloor(p.h) - 1e-9 || !inGamut(p)) return false;
  return p.c >= relative * maxChroma(p.l, p.h) - 1e-9;
}

export function inBand(l: number, ground: Ground): boolean {
  return l >= BANDS[ground].minL - 1e-9 && l <= BANDS[ground].maxL + 1e-9;
}

const r3 = (v: number): number => Math.round(v * 1000) / 1000;

export function column(h: number, ground: Ground, relative = RELATIVE_CHROMA, room = BASE_GAMUT_ROOM): Lch[] {
  const out: Lch[] = [];
  const { minL, maxL } = BANDS[ground];
  if (room > 0 && maxL - Math.max(minL, mudFloor(h)) < BASE_LIGHTNESS_ROOM - 1e-9) return out;
  for (let li = Math.round(minL / STEP); li <= Math.round(maxL / STEP); li++) {
    const l = r3(li * STEP);
    if (l < mudFloor(h) - 1e-9) continue;
    const most = maxChroma(l, h);
    if (most < room) continue;
    for (let ci = Math.round(PALETTE_MIN_CHROMA / STEP); ci * STEP <= most; ci++) {
      const p = { l, c: r3(ci * STEP), h };
      if (p.c >= relative * most - 1e-9 && inGamut(p)) out.push(p);
    }
  }
  return out;
}

const grids = new Map<string, readonly Lch[]>();

export function candidates(ground: Ground): readonly Lch[] {
  let grid = grids.get(ground);
  if (!grid) {
    grid = Array.from({ length: 360 / HUE_STEP }, (_, i) => column(i * HUE_STEP, ground)).flat();
    grids.set(ground, grid);
  }
  return grid;
}

export function shadePool(ground: Ground): readonly Lch[] {
  const key = `shade:${ground}`;
  let grid = grids.get(key);
  if (!grid) {
    grid = Array.from({ length: 360 / HUE_STEP }, (_, i) => column(i * HUE_STEP, ground, SHADE_RELATIVE_CHROMA, 0)).flat();
    grids.set(key, grid);
  }
  return grid;
}

export function farthest(pool: readonly Lch[], taken: readonly Lch[]): Lch | null {
  return byRoom(pool, taken, 1)[0] ?? null;
}

export function byRoom(pool: readonly Lch[], taken: readonly Lch[], limit = Infinity): Lch[] {
  const room = pool.map((p) => {
    let near = Infinity;
    for (const t of taken) near = Math.min(near, deltaE(p, t));
    return near;
  });
  const order = pool.map((_, i) => i);
  if (limit === 1) {
    let best = -1;
    for (const i of order) if (best < 0 || room[i]! > room[best]! + 1e-12) best = i;
    return best < 0 ? [] : [pool[best]!];
  }
  order.sort((i, j) => (Math.abs(room[i]! - room[j]!) <= 1e-12 ? i - j : room[j]! - room[i]!));
  return order.slice(0, limit).map((i) => pool[i]!);
}

export function lchCss(p: Lch): string {
  return `oklch(${r3(p.l)} ${r3(p.c)} ${Math.round(p.h * 10) / 10})`;
}
