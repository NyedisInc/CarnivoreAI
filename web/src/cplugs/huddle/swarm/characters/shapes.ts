
export const SEGMENTS = 48;
const TAU = Math.PI * 2;

type Pt = [number, number];

export type ShapeKey =
  | 'sq' | 'hex' | 'tri' | 'tear' | 'dot' | 'grave' | 'qmark'
  | 'circ' | 'dia' | 'pent' | 'oct' | 'star' | 'shld' | 'cloud';

export const HOME_SHAPES = {
  square: 'sq', circle: 'circ', hexagon: 'hex', triangle: 'tri', diamond: 'dia',
  pentagon: 'pent', octagon: 'oct', star: 'star', shield: 'shld', cloud: 'cloud',
} as const satisfies Record<string, ShapeKey>;

export type HomeShapeName = keyof typeof HOME_SHAPES;
export type HomeShape = (typeof HOME_SHAPES)[HomeShapeName];

export type CoronaKey = 'routine' | 'priority' | 'immediate' | 'flash';

export interface PackShapes {
  pixel: boolean;
  d: Record<ShapeKey, string>;
  pts: Record<ShapeKey, Pt[]>;
  corona: Record<CoronaKey, string>;
  homeLoops: Record<HomeShape, Pt[]>;
  ribbon: string;
  stone: { rip: string; ground: string };
}

function f(v: number): string {
  return String(Math.round(v * 10) / 10);
}

function pt(q: Pt): string {
  return `${f(q[0])} ${f(q[1])}`;
}

function prand(i: number): number {
  const x = Math.sin(i * 91.7 + 13.3) * 43758.5453;
  return x - Math.floor(x);
}

function roundedPolygon(cx: number, cy: number, m: number, R: number, rc: number, a0: number): Pt[] {
  const out: Pt[] = [];
  const h = Math.PI / m;
  const dIn = rc / Math.cos(h);
  for (let k = 0; k < m; k++) {
    const a = a0 + (k * TAU) / m;
    const ox = cx + (R - dIn) * Math.cos(a);
    const oy = cy + (R - dIn) * Math.sin(a);
    for (let j = 0; j <= 12; j++) {
      const b = a - h + (j * h) / 6;
      out.push([ox + rc * Math.cos(b), oy + rc * Math.sin(b)]);
    }
  }
  return out;
}

function polar(cx: number, cy: number, radius: (angle: number) => number): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < 720; i++) {
    const a = -Math.PI / 2 + (i * TAU) / 720;
    const r = radius(a);
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return out;
}

function resample(poly: Pt[], cx: number, n: number): Pt[] {
  let bi = -1;
  let by = Infinity;
  let bp: Pt = [cx, 0];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]!;
    const b = poly[(i + 1) % poly.length]!;
    if (a[0] < b[0] && (a[0] - cx) * (b[0] - cx) <= 0) {
      const t = (cx - a[0]) / (b[0] - a[0]);
      const y = a[1] + t * (b[1] - a[1]);
      if (y < by) {
        by = y;
        bi = i;
        bp = [cx, y];
      }
    }
  }
  const ring: Pt[] = [bp];
  for (let k = 1; k <= poly.length; k++) ring.push(poly[(bi + k) % poly.length]!);
  ring.push(bp);
  const L: number[] = [0];
  for (let i = 1; i < ring.length; i++) {
    L.push(L[i - 1]! + Math.hypot(ring[i]![0] - ring[i - 1]![0], ring[i]![1] - ring[i - 1]![1]));
  }
  const total = L[L.length - 1]!;
  const out: Pt[] = [];
  let j = 1;
  for (let s = 0; s < n; s++) {
    const d = (s * total) / n;
    while (j < L.length - 1 && L[j]! < d) j++;
    const seg = L[j]! - L[j - 1]! || 1;
    const u = (d - L[j - 1]!) / seg;
    const a = ring[j - 1]!;
    const b = ring[j]!;
    out.push([a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])]);
  }
  return out;
}

function toD(P: Pt[], sharp: true | Record<number, 1> | null): string {
  const n = P.length;
  let s = `M${pt(P[0]!)}`;
  for (let i = 0; i < n; i++) {
    const a = P[(i + n - 1) % n]!;
    const b = P[i]!;
    const c = P[(i + 1) % n]!;
    const d = P[(i + 2) % n]!;
    const k1 = sharp === true || (sharp && sharp[i]) ? 0 : 1 / 6;
    const k2 = sharp === true || (sharp && sharp[(i + 1) % n]) ? 0 : 1 / 6;
    s += `C${pt([b[0] + (c[0] - a[0]) * k1, b[1] + (c[1] - a[1]) * k1])} ${pt([c[0] - (d[0] - b[0]) * k2, c[1] - (d[1] - b[1]) * k2])} ${pt(c)}`;
  }
  return `${s}Z`;
}

function snap(P: Pt[]): Pt[] {
  const g = 100 / 12;
  return P.map((q) => [Math.round(q[0] / g) * g, Math.round(q[1] / g) * g] as Pt);
}

const Q_R = 17;
const Q_W = 6.5;
const Q_C: Pt = [50, 32];

function qArc(deg: number, r: number): Pt {
  const a = (deg * Math.PI) / 180;
  return [Q_C[0] + r * Math.cos(a), Q_C[1] + r * Math.sin(a)];
}

function qStem(t: number, side: -1 | 1): Pt {
  const p0 = qArc(390, Q_R);
  const p1: Pt = [p0[0] - 5, p0[1] + 8.7];
  const p2: Pt = [50, 50];
  const p3: Pt = [50, 62];
  const u = 1 - t;
  const x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0];
  const y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1];
  const dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0]);
  const dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1]);
  const l = Math.hypot(dx, dy) || 1;
  return [x + side * Q_W * (dy / l), y - side * Q_W * (dx / l)];
}

function qmarkPoints(): Pt[] {
  const P: Pt[] = [];
  for (let k = 0; k <= 6; k++) P.push(qArc(270 + 20 * k, Q_R + Q_W));
  for (const t of [0.35, 0.7, 1]) P.push(qStem(t, 1));
  P.push([50, 67.5], [50, 74]);
  for (let i = 1; i <= 11; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5.5;
    P.push([50 + 9.5 * Math.cos(a), 83.5 + 9.5 * Math.sin(a)]);
  }
  P.push([50, 74], [50, 67.5]);
  for (const t of [1, 0.65, 0.3]) P.push(qStem(t, -1));
  for (let k = 0; k <= 6; k++) P.push(qArc(390 - 37.5 * k, Q_R - Q_W));
  const end = qArc(165, Q_R);
  for (const deg of [30, 120]) P.push([end[0] + Q_W * Math.cos((deg * Math.PI) / 180), end[1] + Q_W * Math.sin((deg * Math.PI) / 180)]);
  for (let k = 0; k <= 10; k++) P.push(qArc(165 + (105 / 11) * k, Q_R + Q_W));
  return P;
}

const QMARK_SHARP: Record<number, 1> = { 10: 1, 11: 1, 23: 1, 24: 1 };

function rot(p: Pt, cx: number, cy: number, deg: number): Pt {
  const a = (deg * Math.PI) / 180;
  const x = p[0] - cx;
  const y = p[1] - cy;
  return [cx + x * Math.cos(a) - y * Math.sin(a), cy + x * Math.sin(a) + y * Math.cos(a)];
}

const GRAVE_LEAN = -5;

function gravePolygon(): Pt[] {
  const p: Pt[] = [];
  for (let i = 0; i <= 60; i++) {
    const a = Math.PI + (i * Math.PI) / 60;
    p.push([50 + 34 * Math.cos(a), 40 + 34 * Math.sin(a)]);
  }
  p.push([84, 91], [81, 95], [19, 95], [16, 91]);
  return p.map((q) => rot(q, 50, 95, GRAVE_LEAN));
}

function starPolygon(): Pt[] {
  const p: Pt[] = [];
  for (let k = 0; k < 10; k++) {
    const a = -Math.PI / 2 + (k * Math.PI) / 5;
    const r = k % 2 ? 27 : 50;
    p.push([50 + r * Math.cos(a), 54 + r * Math.sin(a)]);
  }
  return p;
}

function shieldPolygon(): Pt[] {
  const right: Pt[] = [[84, 6], [88, 10], [88, 46]];
  for (let i = 1; i <= 12; i++) {
    const t = i / 12;
    right.push([88 - 38 * t * t, 46 + 50 * t]);
  }
  const left = right.slice(0, -1).reverse().map(([x, y]) => [100 - x, y] as Pt);
  return [[50, 6], ...right, ...left];
}

function cloudPolygon(): Pt[] {
  return polar(50, 56, (a) => (Math.sin(a) < 0 ? 38 + 10 * Math.abs(Math.cos(3.5 * (a + Math.PI / 2))) : Math.min(44, 30 / Math.sin(a))));
}

function stoneMarks(): { rip: string; ground: string } {
  const lean = (x: number, y: number): string => pt(rot([x, y], 50, 95, GRAVE_LEAN));
  const run = (cmds: [string, number, number][]): string => cmds.map(([c, x, y]) => `${c}${lean(x, y)}`).join('');
  const cross = run([['M', 50, 20], ['L', 50, 40], ['M', 42, 27], ['L', 58, 27]]);
  const rip = run([
    ['M', 29, 74], ['L', 29, 56], ['L', 35, 56], ['L', 37, 58], ['L', 37, 62], ['L', 35, 64], ['L', 29, 64], ['M', 33, 64], ['L', 38, 74],
    ['M', 46, 56], ['L', 46, 74],
    ['M', 54, 74], ['L', 54, 56], ['L', 60, 56], ['L', 62, 58], ['L', 62, 62], ['L', 60, 64], ['L', 54, 64],
  ]);
  return { rip: cross + rip, ground: 'M2 97.5H98M14 97.5L11 91M18 97.5L19 90M84 97.5L82 91M89 97.5L92 92' };
}

function lengths(loop: Pt[]): { cum: number[]; total: number } {
  const cum = [0];
  for (let i = 1; i <= loop.length; i++) cum.push(cum[i - 1]! + Math.hypot(loop[i % loop.length]![0] - loop[i - 1]![0], loop[i % loop.length]![1] - loop[i - 1]![1]));
  return { cum, total: cum[loop.length]! };
}

function at(loop: Pt[], cum: number[], total: number, s: number): { p: Pt; n: Pt } {
  const u = ((s % total) + total) % total;
  let i = 0;
  while (i < loop.length - 1 && cum[i + 1]! < u) i++;
  const a = loop[i]!;
  const b = loop[(i + 1) % loop.length]!;
  const t = (u - cum[i]!) / (cum[i + 1]! - cum[i]! || 1);
  const tx = b[0] - a[0];
  const ty = b[1] - a[1];
  const l = Math.hypot(tx, ty) || 1;
  return { p: [a[0] + t * tx, a[1] + t * ty], n: [ty / l, -tx / l] };
}

interface Spikes {
  n: number;
  L: number;
  hw: number;
  ins: number;
  soft: boolean;
  jit?: number;
  sec?: number;
}

function spikePath(loops: Pt[][], r: Spikes, phase: number, pixel: boolean): string {
  const tot = loops.reduce((s, l) => s + lengths(l).total, 0);
  let out = '';
  loops.forEach((loop) => {
    const { cum, total } = lengths(loop);
    const n = Math.max(3, Math.round((r.n * total) / tot));
    const pts: Pt[] = [];
    const tip = (s: number, len: number, rotA: number): Pt => {
      const q = at(loop, cum, total, s);
      const c = Math.cos(rotA);
      const sn = Math.sin(rotA);
      return [q.p[0] + (q.n[0] * c - q.n[1] * sn) * len, q.p[1] + (q.n[0] * sn + q.n[1] * c) * len];
    };
    const base = (s: number): Pt => {
      const q = at(loop, cum, total, s);
      return [q.p[0] - q.n[0] * r.ins, q.p[1] - q.n[1] * r.ins];
    };
    for (let k = 0; k < n; k++) {
      const s = ((phase + k / n) % 1) * total;
      const len = r.jit ? r.L * (1 + r.jit * (prand(k) - 0.5)) : r.L;
      if (r.soft) {
        for (let i = 0; i <= 20; i++) {
          const t = -1 + i / 10;
          const q = at(loop, cum, total, s + t * r.hw);
          const g = 0.5 + 0.5 * Math.cos(Math.PI * t);
          const d = -r.ins + (len + r.ins) * g;
          pts.push([q.p[0] + q.n[0] * d, q.p[1] + q.n[1] * d]);
        }
      } else {
        pts.push(base(s - r.hw), tip(s, len, r.jit ? (prand(k + 40) - 0.5) * 0.4 : 0), base(s + r.hw));
      }
      if (r.sec) {
        const m = s + total / (2 * n);
        pts.push(base(m - r.hw * 0.45), tip(m, r.sec * (0.8 + 0.4 * prand(k + 90)), 0), base(m + r.hw * 0.45));
      }
    }
    out += `M${(pixel ? snap(pts) : pts).map(pt).join('L')}Z`;
  });
  return out;
}

function coronasOn(loop: Pt[], pixel: boolean): Record<CoronaKey, string> {
  const per = lengths(loop).total;
  return {
    routine: spikePath([loop], pixel ? { n: 16, L: 9, hw: per / 80, ins: 1, soft: false } : { n: 24, L: 6.5, hw: per / 96, ins: 2, soft: true }, 0.125, pixel),
    priority: spikePath([loop], { n: 12, L: 14, hw: per / 34, ins: 3, soft: true }, 0.125, pixel),
    immediate: spikePath([loop], { n: 12, L: 23, hw: per / 42, ins: 3, soft: false }, 0.125, pixel),
    flash: spikePath([loop], { n: 12, L: 36, hw: per / 38, ins: 3, soft: false, jit: 0.5, sec: 14 }, 0.125, pixel),
  };
}

const coronaMemo = new WeakMap<PackShapes, Map<HomeShape, Record<CoronaKey, string>>>();

export function coronaFor(shapes: PackShapes, home: HomeShape): Record<CoronaKey, string> {
  if (home === 'sq') return shapes.corona;
  let byHome = coronaMemo.get(shapes);
  if (!byHome) coronaMemo.set(shapes, (byHome = new Map()));
  let c = byHome.get(home);
  if (!c) byHome.set(home, (c = coronasOn(shapes.homeLoops[home], shapes.pixel)));
  return c;
}

export function buildShapes(pixel: boolean): PackShapes {
  const sqPoly = roundedPolygon(50, 50, 4, 50 * Math.SQRT2, pixel ? 8 : 22, -Math.PI / 4);
  const tearR = (a: number): number => {
    const d = Math.atan2(Math.sin(a - 2.2), Math.cos(a - 2.2));
    const g = Math.max(0, 1 - Math.abs(d) / 1.1);
    return 44 * (1 + 0.46 * g * g);
  };
  const homes: Record<HomeShape, Pt[]> = {
    sq: sqPoly,
    circ: polar(50, 50, () => 47),
    hex: roundedPolygon(50, 50, 6, 58, pixel ? 6 : 12, -Math.PI / 2),
    tri: roundedPolygon(50, 56, 3, 74, pixel ? 8 : 14, -Math.PI / 2),
    dia: roundedPolygon(50, 50, 4, 58, pixel ? 6 : 12, -Math.PI / 2),
    pent: roundedPolygon(50, 53, 5, 54, pixel ? 6 : 12, -Math.PI / 2),
    oct: roundedPolygon(50, 50, 8, 52, pixel ? 4 : 8, -Math.PI / 2 + Math.PI / 8),
    star: starPolygon(),
    shld: shieldPolygon(),
    cloud: cloudPolygon(),
  };
  const raw: Record<ShapeKey, Pt[]> = {
    sq: resample(homes.sq, 50, SEGMENTS),
    hex: resample(homes.hex, 50, SEGMENTS),
    tri: resample(homes.tri, 50, SEGMENTS),
    circ: resample(homes.circ, 50, SEGMENTS),
    dia: resample(homes.dia, 50, SEGMENTS),
    pent: resample(homes.pent, 50, SEGMENTS),
    oct: resample(homes.oct, 50, SEGMENTS),
    star: resample(homes.star, 50, SEGMENTS),
    shld: resample(homes.shld, 50, SEGMENTS),
    cloud: resample(homes.cloud, 50, SEGMENTS),
    tear: resample(polar(52, 45, tearR), 52, SEGMENTS),
    dot: resample(polar(50, 70, () => 17), 50, SEGMENTS),
    grave: resample(gravePolygon(), 50, SEGMENTS),
    qmark: qmarkPoints(),
  };
  const sharpOf: Partial<Record<ShapeKey, Record<number, 1>>> = { qmark: QMARK_SHARP };
  const pts = {} as Record<ShapeKey, Pt[]>;
  const d = {} as Record<ShapeKey, string>;
  for (const k of Object.keys(raw) as ShapeKey[]) {
    pts[k] = pixel ? snap(raw[k]) : raw[k];
    d[k] = toD(pts[k], pixel ? true : sharpOf[k] ?? null);
  }
  const ribbon = ((): string => {
    const o: Pt[] = [];
    const q: Pt[] = [];
    const span = 2.3;
    const n = 30;
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const a = -span + t * span;
      const w = 1.4 + 11 * Math.pow(t, 1.5);
      o.push([(60 + w / 2) * Math.cos(a), (60 + w / 2) * Math.sin(a)]);
      q.push([(60 - w / 2) * Math.cos(a), (60 - w / 2) * Math.sin(a)]);
    }
    const cap: Pt[] = [];
    for (let i = 1; i < 8; i++) {
      const b = (i * Math.PI) / 8;
      cap.push([60 + 6.2 * Math.cos(b), 6.2 * Math.sin(b)]);
    }
    return `M${o.concat(cap, q.reverse()).map(pt).join('L')}Z`;
  })();
  const homeLoops = {} as Record<HomeShape, Pt[]>;
  for (const k of Object.keys(homes) as HomeShape[]) homeLoops[k] = resample(homes[k], 50, 1440);
  return {
    pixel,
    d,
    pts,
    corona: coronasOn(homeLoops.sq, pixel),
    homeLoops,
    ribbon,
    stone: stoneMarks(),
  };
}

function blend(A: Pt[], B: Pt[], t: number): Pt[] {
  return A.map((p, i) => [p[0] + (B[i]![0] - p[0]) * t, p[1] + (B[i]![1] - p[1]) * t] as Pt);
}

export function pixelBlendD(shapes: PackShapes, a: ShapeKey, b: ShapeKey, t: number): string {
  return toD(snap(blend(shapes.pts[a], shapes.pts[b], t)), true);
}

const memo = new Map<boolean, PackShapes>();

export function shapesFor(pixel: boolean): PackShapes {
  let s = memo.get(pixel);
  if (!s) {
    s = buildShapes(pixel);
    memo.set(pixel, s);
  }
  return s;
}
