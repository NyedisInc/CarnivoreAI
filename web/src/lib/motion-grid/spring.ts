
export const K = {
  pos: [300, 33],
  size: [300, 33],
  rot: [220, 26],
  sc: [260, 28],
  op: [200, 28],
  drop: [430, 37],
} as const;

export type SpringKind = keyof typeof K;

export interface Spring {
  v: number;
  t: number;
  vel: number;
  k: number;
  c: number;
}

export function makeSpring(v: number, kind: SpringKind): Spring {
  return { v, t: v, vel: 0, k: K[kind][0], c: K[kind][1] };
}

export function setKind(s: Spring, kind: SpringKind): void {
  s.k = K[kind][0];
  s.c = K[kind][1];
}

export function snapTo(s: Spring, v: number): void {
  s.v = v;
  s.t = v;
  s.vel = 0;
}

export function springActive(s: Spring): boolean {
  return s.v !== s.t || s.vel !== 0;
}

export function stepSpring(s: Spring, dt: number, snap: boolean): boolean {
  if (!springActive(s)) return false;
  if (snap) {
    snapTo(s, s.t);
    return false;
  }
  s.vel += (-s.k * (s.v - s.t) - s.c * s.vel) * dt;
  s.v += s.vel * dt;
  if (Math.abs(s.v - s.t) < 0.04 && Math.abs(s.vel) < 0.6) {
    snapTo(s, s.t);
    return false;
  }
  return true;
}
