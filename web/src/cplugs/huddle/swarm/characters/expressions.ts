import type { CharacterState } from './states';

export type EyeShape = 'bar' | 'dot' | 'arch' | 'cup' | 'lidt' | 'lidb' | 'slant' | 'gt' | 'cross' | 'heart' | 'star' | 'ring';

export type EyeMotion =
  | 'none' | 'sweep' | 'dart' | 'roll' | 'orbit' | 'shake' | 'bob' | 'pulse' | 'twinkle' | 'tilt' | 'droop' | 'sob' | 'glance' | 'sigh' | 'lift';

export interface Eye {
  shape: EyeShape;
  w: number;
  h: number;
  x: number;
  y: number;
  r: number;
  flip: boolean;
}

export interface Expression {
  name: string;
  l: Eye;
  r: Eye;
  motion: EyeMotion;
  ms: number;
}

const BASE_W = 0.1;
const BASE_H = 0.24;

const SHAPES: Record<EyeShape, { smooth: string; pixel: string; bg?: string }> = {
  bar: { smooth: 'none', pixel: 'none' },
  dot: { smooth: 'ellipse(50% 50% at 50% 50%)', pixel: 'polygon(25% 0,75% 0,75% 25%,100% 25%,100% 75%,75% 75%,75% 100%,25% 100%,25% 75%,0 75%,0 25%,25% 25%)' },
  arch: {
    smooth: 'polygon(0 75%,50% 20%,100% 75%,100% 100%,50% 45%,0 100%)',
    pixel: 'polygon(40% 0,60% 0,60% 20%,80% 20%,80% 40%,100% 40%,100% 80%,80% 80%,80% 60%,60% 60%,60% 40%,40% 40%,40% 60%,20% 60%,20% 80%,0 80%,0 40%,20% 40%,20% 20%,40% 20%)',
  },
  cup: {
    smooth: 'polygon(0 0,50% 55%,100% 0,100% 25%,50% 80%,0 25%)',
    pixel: 'polygon(0 20%,20% 20%,20% 40%,40% 40%,40% 60%,60% 60%,60% 40%,80% 40%,80% 20%,100% 20%,100% 60%,80% 60%,80% 80%,60% 80%,60% 100%,40% 100%,40% 80%,20% 80%,20% 60%,0 60%)',
  },
  lidt: { smooth: 'polygon(0 40%,100% 40%,100% 100%,0 100%)', pixel: 'polygon(0 40%,100% 40%,100% 100%,0 100%)' },
  lidb: { smooth: 'polygon(0 0,100% 0,100% 60%,0 60%)', pixel: 'polygon(0 0,100% 0,100% 60%,0 60%)' },
  slant: { smooth: 'polygon(0 0,100% 40%,100% 100%,0 100%)', pixel: 'polygon(0 0,40% 0,40% 20%,80% 20%,80% 40%,100% 40%,100% 100%,0 100%)' },
  gt: {
    smooth: 'polygon(0 0,25% 0,75% 50%,25% 100%,0 100%,50% 50%)',
    pixel: 'polygon(0 0,25% 0,50% 25%,75% 50%,50% 75%,25% 100%,0 100%,25% 75%,50% 50%,25% 25%)',
  },
  cross: {
    smooth: 'polygon(0 12%,12% 0,50% 38%,88% 0,100% 12%,62% 50%,100% 88%,88% 100%,50% 62%,12% 100%,0 88%,38% 50%)',
    pixel: 'polygon(0 0,30% 0,50% 20%,70% 0,100% 0,100% 30%,80% 50%,100% 70%,100% 100%,70% 100%,50% 80%,30% 100%,0 100%,0 70%,20% 50%,0 30%)',
  },
  heart: {
    smooth: 'polygon(50% 100%,12% 62%,0 40%,0 22%,12% 6%,30% 0,45% 8%,50% 20%,55% 8%,70% 0,88% 6%,100% 22%,100% 40%,88% 62%)',
    pixel: 'polygon(0 20%,20% 20%,20% 0,40% 0,40% 20%,60% 20%,60% 0,80% 0,80% 20%,100% 20%,100% 60%,80% 60%,80% 80%,60% 80%,60% 100%,40% 100%,40% 80%,20% 80%,20% 60%,0 60%)',
  },
  star: {
    smooth: 'polygon(50% 0,62% 36%,100% 38%,70% 60%,80% 100%,50% 76%,20% 100%,30% 60%,0 38%,38% 36%)',
    pixel: 'polygon(40% 0,60% 0,60% 30%,100% 30%,100% 50%,70% 60%,80% 100%,50% 75%,20% 100%,30% 60%,0 50%,0 30%,40% 30%)',
  },
  ring: {
    smooth: 'ellipse(50% 50% at 50% 50%)',
    pixel: 'polygon(0 0,100% 0,100% 100%,0 100%,0 50%,30% 50%,30% 70%,70% 70%,70% 30%,30% 30%,30% 50%,0 50%)',
    bg: 'radial-gradient(ellipse at center,transparent 0 34%,var(--oc-on-accent) 36%)',
  },
};

function eye(shape: EyeShape, w: number, h: number, x = 0, y = 0, r = 0): Eye {
  return { shape, w, h, x, y, r, flip: false };
}
function mir(e: Eye): Eye {
  return { ...e, x: -e.x, r: -e.r, flip: !e.flip };
}
function sym(name: string, e: Eye, motion: EyeMotion, ms: number): Expression {
  return { name, l: e, r: mir(e), motion, ms };
}
function same(name: string, e: Eye, motion: EyeMotion, ms: number): Expression {
  return { name, l: e, r: { ...e }, motion, ms };
}
function pair(name: string, l: Eye, r: Eye, motion: EyeMotion, ms: number): Expression {
  return { name, l, r, motion, ms };
}

export const EXPRESSIONS: readonly Expression[] = [
  sym('happy', eye('arch', 0.2, 0.14, 0, 0.01), 'none', 1800),
  sym('delighted', eye('arch', 0.24, 0.2, 0, -0.03), 'bob', 2000),
  sym('laughing', eye('gt', 0.15, 0.15), 'shake', 1800),
  sym('content', eye('cup', 0.18, 0.1), 'none', 2200),
  sym('relieved', eye('arch', 0.16, 0.1, 0, 0.02), 'sigh', 2200),
  same('proud', eye('lidb', 0.13, 0.3, 0, -0.04), 'lift', 2000),
  same('smug', eye('lidt', 0.15, 0.12, 0.03, 0.01), 'glance', 2000),
  same('sleepy', eye('lidt', 0.17, 0.1, 0, 0.04), 'droop', 2400),
  same('bored', eye('lidt', 0.1, 0.22, -0.03, 0.03), 'sweep', 2400),
  same('deadpan', eye('dot', 0.06, 0.06), 'none', 1800),
  same('annoyed', eye('lidt', 0.15, 0.11), 'roll', 2400),
  pair('skeptical', eye('bar', 0.1, 0.28, 0, -0.04), eye('lidt', 0.13, 0.12, 0, 0.02), 'none', 2000),
  pair('doubtful', eye('slant', 0.12, 0.16), eye('bar', 0.1, 0.2, 0, -0.03), 'tilt', 2000),
  same('side-eye left', eye('bar', 0.08, 0.2, -0.1), 'none', 1600),
  same('side-eye right', eye('bar', 0.08, 0.2, 0.1), 'none', 1600),
  pair('suspicious', eye('bar', 0.16, 0.05, 0, 0.01), eye('bar', 0.12, 0.09, 0, -0.01), 'sweep', 2000),
  same('focused', eye('bar', 0.15, 0.07), 'none', 2000),
  same('thinking', eye('bar', 0.09, 0.2, -0.04, -0.07), 'none', 2200),
  same('curious', eye('dot', 0.15, 0.15), 'tilt', 2000),
  pair('confused', eye('bar', 0.1, 0.3, 0, -0.04), eye('bar', 0.1, 0.12, 0, 0.04), 'tilt', 2200),
  same('surprised', eye('dot', 0.14, 0.24), 'lift', 1400),
  same('shocked', eye('ring', 0.22, 0.22), 'shake', 1600),
  sym('scared', eye('bar', 0.07, 0.34, 0.05), 'shake', 1800),
  same('nervous', eye('dot', 0.11, 0.15), 'dart', 2200),
  sym('sad', eye('bar', 0.09, 0.22, 0, 0, 16), 'none', 2200),
  sym('worried', eye('bar', 0.09, 0.26, 0, -0.01, 22), 'sob', 2000),
  same('crying', eye('ring', 0.11, 0.11, 0, 0.03), 'sob', 2200),
  same('heartbroken', eye('heart', 0.16, 0.16, 0, 0.02), 'droop', 2400),
  sym('angry', eye('slant', 0.12, 0.2), 'none', 1800),
  sym('furious', eye('slant', 0.15, 0.28), 'shake', 1800),
  sym('grumpy', eye('slant', 0.14, 0.12, 0, 0.04), 'sigh', 2000),
  sym('determined', eye('slant', 0.09, 0.22, 0, -0.01, 14), 'pulse', 2000),
  pair('mischievous', eye('slant', 0.14, 0.14), eye('arch', 0.18, 0.12), 'none', 2000),
  sym('disgusted', eye('lidt', 0.13, 0.12, 0, 0.02, 10), 'glance', 2000),
  pair('wink left', eye('arch', 0.16, 0.1), eye('bar', 0.11, 0.26), 'none', 1500),
  pair('wink right', eye('bar', 0.11, 0.26), eye('arch', 0.16, 0.1), 'none', 1500),
  same('love-struck', eye('heart', 0.2, 0.2), 'pulse', 2200),
  same('starry', eye('star', 0.22, 0.22), 'twinkle', 2200),
  same('knocked out', eye('cross', 0.16, 0.16), 'none', 2000),
  same('dizzy', eye('ring', 0.17, 0.17), 'orbit', 2400),
  same('excited', eye('bar', 0.14, 0.36), 'bob', 1800),
  same('embarrassed', eye('lidt', 0.1, 0.14, -0.07, 0.04), 'glance', 2000),
  same('eye-roll', eye('bar', 0.1, 0.22), 'roll', 1800),
  same('shy', eye('arch', 0.12, 0.08, 0.05, 0.04), 'glance', 2200),
  same('hopeful', eye('dot', 0.13, 0.19, 0, -0.05), 'pulse', 2000),
  same('aww', eye('cup', 0.22, 0.16, 0, 0.02), 'pulse', 2400),
  same('sneaky', eye('slant', 0.13, 0.1, -0.05), 'sweep', 2200),
  same('daydreaming', eye('dot', 0.16, 0.16, 0.06, -0.07), 'sweep', 2500),
  same('dazzled', eye('star', 0.13, 0.13, 0, -0.02), 'dart', 2000),
  sym('smirking', eye('lidb', 0.15, 0.16, 0, -0.01), 'glance', 2000),
];

export const EXPR_MIN_MS = 120_000;
export const EXPR_MAX_MS = 180_000;
export const RESTING: ReadonlySet<CharacterState> = new Set<CharacterState>(['idle', 'finished_unread']);
export const SETTLE_MS = 3000;

export interface Candidate {
  state: CharacterState;
  still: boolean;
  visible: boolean;
  ageMs: number;
}

export function nextDelay(r: () => number): number {
  return EXPR_MIN_MS + r() * (EXPR_MAX_MS - EXPR_MIN_MS);
}

export function eligible(c: Candidate): boolean {
  return !c.still && c.visible && RESTING.has(c.state) && c.ageMs >= SETTLE_MS;
}

export function pickCharacter(cands: readonly Candidate[], r: () => number): number {
  const ok = cands.flatMap((c, i) => (eligible(c) ? [i] : []));
  return ok.length ? ok[Math.min(ok.length - 1, Math.floor(r() * ok.length))]! : -1;
}

export function pickExpression(prev: string | null, r: () => number): Expression {
  const pool = EXPRESSIONS.filter((x) => x.name !== prev);
  return pool[Math.min(pool.length - 1, Math.floor(r() * pool.length))]!;
}

function eyeVars(side: 'l' | 'r', e: Eye, pixel: boolean): Record<string, string> {
  const s = SHAPES[e.shape];
  const p = `--f${side}-`;
  return {
    [`${p}x`]: String(e.x),
    [`${p}y`]: String(e.y),
    [`${p}r`]: String(e.r),
    [`${p}sx`]: String((e.w / BASE_W) * (e.flip ? -1 : 1)),
    [`${p}sy`]: String(e.h / BASE_H),
    [`${p}clip`]: pixel ? s.pixel : s.smooth,
    [`${p}bg`]: s.bg && !pixel ? s.bg : 'var(--oc-on-accent)',
  };
}

const VAR_NAMES = ['x', 'y', 'r', 'sx', 'sy', 'clip', 'bg'].flatMap((n) => [`--fl-${n}`, `--fr-${n}`]);

export function applyExpression(el: HTMLElement, x: Expression, pixel: boolean): void {
  for (const [k, v] of Object.entries({ ...eyeVars('l', x.l, pixel), ...eyeVars('r', x.r, pixel) })) el.style.setProperty(k, v);
  el.style.setProperty('--fd', `${x.ms / 1000}s`);
  el.style.setProperty('--gx', '0');
  el.style.setProperty('--gy', '0');
  el.setAttribute('data-fm', x.motion);
  el.setAttribute('data-fx', x.name);
}

export function clearExpression(el: HTMLElement): void {
  for (const k of VAR_NAMES) el.style.removeProperty(k);
  el.style.removeProperty('--fd');
  el.removeAttribute('data-fm');
  el.removeAttribute('data-fx');
}
