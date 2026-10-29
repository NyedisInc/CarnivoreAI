import { applyExpression, clearExpression, nextDelay, pickCharacter, pickExpression, type Expression } from './expressions';
import { STATES, type CharacterState, type GazePolicy } from './states';
import { animationTypeOff, watchAnimationTypes } from '../../../../lib/motion/animation-types';
import { motionReduced, watchMotion } from '../../../../lib/motion/motion';
import { watchWindowCalm, windowCalm } from '../../../sdk';

export const TICK_MS = 250;
const MAX_SLEEP_MS = 2000;

export type Rng = () => number;

interface Entry {
  el: HTMLElement;
  state: () => CharacterState;
  side: () => 'l' | 'r';
  t0: number;
  nextGaze: number;
  nextBlink: number;
  blinkEnd: number;
  secondBlink: number;
  nextQuirk: number;
  quirkEnd: number;
  gx: number | null;
  gy: number | null;
  readDir: number;
  exEnd: number;
}

export interface PackClock {
  register(el: HTMLElement, state: () => CharacterState, side?: () => 'l' | 'r'): () => void;
  play(el: HTMLElement, x: Expression): void;
  reset(el: HTMLElement): void;
  setPaused(paused: boolean): void;
  isPaused(): boolean;
  tick(): void;
  size(): number;
}

export function nextGaze(policy: GazePolicy, side: 'l' | 'r', readDir: number, r: Rng): [number, number, number, number] {
  const span = (a: number, b: number): number => a + r() * (b - a);
  switch (policy) {
    case 'read': {
      const dir = -readDir;
      return [Math.round((dir + (r() - 0.5) * 0.2) * 100) / 100, 0.55, span(650, 1100), dir];
    }
    case 'up':
      return r() < 0.22
        ? [r() < 0.5 ? -0.7 : 0.7, -0.3, span(500, 800), readDir]
        : [Math.round((r() - 0.5) * 30) / 100, -0.7, span(1600, 3000), readDir];
    case 'you':
      return r() < 0.25
        ? [r() < 0.5 ? -0.8 : 0.8, Math.round((r() - 0.5) * 60) / 100, span(450, 800), readDir]
        : [0, -0.12, span(1800, 3400), readDir];
    case 'upleft':
      return [-0.6, -0.85, Infinity, readDir];
    case 'partner':
      return [side === 'r' ? -0.95 : 0.95, 0, Infinity, readDir];
    case 'dart':
      return [Math.round((r() * 2 - 1) * 100) / 100, Math.round((r() * 2 - 1) * 80) / 100, span(140, 360), readDir];
    default:
      return r() < 0.35
        ? [0, 0, span(1200, 3200), readDir]
        : [Math.round((r() * 2 - 1) * 100) / 100, Math.round((r() * 2 - 1) * 70) / 100, span(1200, 3600), readDir];
  }
}

export function createClock(r: Rng = Math.random, isVisible: (el: HTMLElement) => boolean = onScreen): PackClock {
  const entries = new Map<HTMLElement, Entry>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let armedAt = 0;
  let armedDelay = 0;
  let paused = false;
  let T = 0;
  let nextExpr = nextDelay(r);
  let lastExpr: string | null = null;
  const span = (a: number, b: number): number => a + r() * (b - a);

  const put = (el: HTMLElement, name: string, v: number): void => el.style.setProperty(name, String(v));
  const clearQuirk = (el: HTMLElement): void => {
    for (const v of ['--qy', '--qr', '--qsx', '--qsy']) el.style.removeProperty(v);
  };
  const quirk = (el: HTMLElement): void => {
    const k = Math.floor(r() * 3);
    if (k === 0) put(el, '--qy', -0.06);
    else if (k === 1) put(el, '--qr', (r() < 0.5 ? -1 : 1) * 6);
    else {
      put(el, '--qsx', 1.06);
      put(el, '--qsy', 0.92);
    }
  };

  const fresh = (el: HTMLElement, state: () => CharacterState, side: () => 'l' | 'r'): Entry => ({
    el,
    state,
    side,
    t0: T,
    nextGaze: 0,
    nextBlink: T + span(800, 4000),
    blinkEnd: 0,
    secondBlink: 0,
    nextQuirk: T + span(6000, 16000),
    quirkEnd: 0,
    gx: null,
    gy: null,
    readDir: 0.4,
    exEnd: 0,
  });

  const bodies = (): SVGSVGElement[] =>
    [...entries.keys()].map((el) => el.querySelector('svg.pk-bd') as SVGSVGElement | null).filter((s): s is SVGSVGElement => !!s);

  const stop = (): void => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const nextDelay_ = (): number | null => {
    if (paused) return null;
    let exact = Infinity;
    let grid = Infinity;
    let live = false;
    const g = (t: number): void => {
      if (t && t < grid) grid = t;
    };
    const x = (t: number): void => {
      if (t && t < exact) exact = t;
    };
    for (const e of entries.values()) {
      if (e.el.hasAttribute('data-still')) continue;
      live = true;
      if (e.exEnd) {
        g(e.exEnd);
        continue;
      }
      const def = STATES[e.state()];
      if (def.breath) {
        g(e.nextQuirk);
        g(e.quirkEnd);
        continue;
      }
      if (def.release && T - e.t0 <= def.release * 1000) g(e.t0 + def.release * 1000 + 1);
      const policy: GazePolicy = def.release && T - e.t0 > def.release * 1000 ? 'wander' : def.gaze;
      if (policy === 'none') continue;
      if (Number.isFinite(e.nextGaze)) g(e.nextGaze || 1);
      g(e.nextBlink);
      x(e.blinkEnd);
      x(e.secondBlink);
      if (def.quirk) {
        g(e.nextQuirk);
        x(e.quirkEnd);
      }
    }
    if (!live) return null;
    g(nextExpr);
    const now = Date.now();
    const rem = Math.max(0, grid - T);
    const wake = Math.max(Math.ceil((now + rem) / TICK_MS) * TICK_MS, 0);
    let delay = wake - now;
    if (delay <= 0) delay = TICK_MS;
    if (Number.isFinite(exact)) delay = Math.min(delay, Math.max(1, exact - T));
    return Math.min(delay, MAX_SLEEP_MS);
  };

  /* there is nothing */
  const arm = (): void => {
    if (timer !== null) T += Math.max(0, Math.min(Date.now() - armedAt, armedDelay));
    stop();
    const delay = nextDelay_();
    if (delay === null) return;
    armedAt = Date.now();
    armedDelay = delay;
    timer = setTimeout(() => {
      timer = null;
      T += delay;
      step();
      arm();
    }, delay);
  };

  const settle = (): void => {
    for (const e of entries.values()) {
      if (e.blinkEnd || e.secondBlink) e.el.style.removeProperty('--bl');
      if (e.quirkEnd) {
        if (STATES[e.state()].breath) e.el.style.removeProperty('--qsy');
        else clearQuirk(e.el);
      }
      e.blinkEnd = 0;
      e.secondBlink = 0;
      e.quirkEnd = 0;
    }
  };

  const clock: PackClock = {
    register(el, state, side = () => 'l') {
      entries.set(el, fresh(el, state, side));
      arm();
      return () => {
        entries.delete(el);
        arm();
      };
    },
    play(el, x) {
      const e = entries.get(el);
      if (!e || el.hasAttribute('data-still')) return;
      applyExpression(el, x, el.getAttribute('data-pack') === 'pixel');
      e.exEnd = T + x.ms;
      arm();
    },
    reset(el) {
      const e = entries.get(el);
      if (!e) return;
      if (e.exEnd) clearExpression(el);
      Object.assign(e, fresh(el, e.state, e.side));
      for (const v of ['--bl', '--qy', '--qr', '--qsx', '--qsy']) el.style.removeProperty(v);
      arm();
    },
    setPaused(p) {
      if (p && !paused) settle();
      paused = p;
      if (typeof document !== 'undefined') document.documentElement.toggleAttribute('data-paused', p);
      for (const svg of bodies()) {
        try {
          if (p) svg.pauseAnimations();
          else svg.unpauseAnimations();
        } catch (e) {
          void e;
        }
      }
      arm();
    },
    isPaused: () => paused,
    size: () => entries.size,
    tick() {
      if (paused) return;
      T += TICK_MS;
      step();
      arm();
    },
  };

  function step(): void {
    if (T >= nextExpr) {
      nextExpr = T + nextDelay(r);
      const list = [...entries.values()];
      const i = pickCharacter(
        list.map((e) => ({
          state: e.state(),
          still: e.el.hasAttribute('data-still'),
          visible: isVisible(e.el),
          ageMs: T - e.t0,
        })),
        r,
      );
      if (i >= 0) {
        const x = pickExpression(lastExpr, r);
        lastExpr = x.name;
        clock.play(list[i]!.el, x);
      }
    }
    for (const e of entries.values()) {
      const el = e.el;
      if (el.hasAttribute('data-still')) continue;
      if (e.exEnd) {
        if (T >= e.exEnd) {
          clearExpression(el);
          e.exEnd = 0;
          e.nextGaze = 0;
          e.gx = null;
          e.gy = null;
        }
        continue;
      }
      const def = STATES[e.state()];
      if (def.breath) {
        if (T >= e.nextQuirk) {
          put(el, '--qsy', 1.04);
          e.quirkEnd = T + 1500;
          e.nextQuirk = T + span(5000, 9000);
        } else if (e.quirkEnd && T >= e.quirkEnd) {
          el.style.removeProperty('--qsy');
          e.quirkEnd = 0;
        }
        continue;
      }
      const policy: GazePolicy = def.release && T - e.t0 > def.release * 1000 ? 'wander' : def.gaze;
      if (policy === 'none') continue;
      if (T >= e.nextGaze) {
        const [x, y, dwell, dir] = nextGaze(policy, e.side(), e.readDir, r);
        e.readDir = dir;
        if (e.gx !== x) {
          put(el, '--gx', x);
          e.gx = x;
        }
        if (e.gy !== y) {
          put(el, '--gy', y);
          e.gy = y;
        }
        e.nextGaze = T + dwell;
      }
      if (T >= e.nextBlink) {
        put(el, '--bl', 0.1);
        e.blinkEnd = T + 110;
        e.secondBlink = r() < 0.18 ? T + 300 : 0;
        e.nextBlink = T + span(2600, 6400);
      } else if (e.blinkEnd && T >= e.blinkEnd) {
        el.style.removeProperty('--bl');
        e.blinkEnd = 0;
      } else if (e.secondBlink && T >= e.secondBlink) {
        put(el, '--bl', 0.1);
        e.blinkEnd = T + 100;
        e.secondBlink = 0;
      }
      if (def.quirk) {
        if (T >= e.nextQuirk) {
          quirk(el);
          e.quirkEnd = T + 240;
          e.nextQuirk = T + span(9000, 20000);
        } else if (e.quirkEnd && T >= e.quirkEnd) {
          clearQuirk(el);
          e.quirkEnd = 0;
        }
      }
    }
  }
  return clock;
}

function onScreen(el: HTMLElement): boolean {
  if (!el.isConnected) return false;
  const b = el.getBoundingClientRect();
  return b.width > 0 && b.height > 0 && b.bottom > 0 && b.right > 0 && b.top < window.innerHeight && b.left < window.innerWidth;
}

export const packClock: PackClock = createClock();

let watching = false;

export function watchVisibility(): void {
  if (watching || typeof document === 'undefined') return;
  watching = true;
  const sync = (): void => packClock.setPaused(document.hidden || motionReduced() || animationTypeOff('swarm-characters') || windowCalm());
  document.addEventListener('visibilitychange', sync);
  watchMotion(sync);
  watchWindowCalm(sync);
  watchAnimationTypes(sync);
  sync();
}
