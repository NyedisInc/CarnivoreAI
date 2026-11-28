import { packClock } from './clock';
import { coronaFor, pixelBlendD, type HomeShape, type PackShapes, type ShapeKey } from './shapes';
import { heldShape, planMorph, STATES, type CharacterState } from './states';

const NS = 'http://www.w3.org/2000/svg';

export interface DefIds {
  cor: Record<'routine' | 'priority' | 'immediate' | 'flash', string>;
  rib: string;
  cmt: string;
}

export function defIds(packId: string, home: HomeShape = 'sq'): DefIds {
  const cor = home === 'sq' ? `pk-${packId}-cor` : `pk-${packId}-${home}-cor`;
  return {
    cor: {
      routine: `${cor}-routine`,
      priority: `${cor}-priority`,
      immediate: `${cor}-immediate`,
      flash: `${cor}-flash`,
    },
    rib: `pk-${packId}-rib`,
    cmt: 'pk-cmt',
  };
}

export function ensureDefs(shapes: PackShapes, packId: string, home: HomeShape = 'sq'): DefIds {
  const ids = defIds(packId, home);
  if (typeof document === 'undefined') return ids;
  let host = document.getElementById('pk-defs');
  if (!host) {
    host = document.createElementNS(NS, 'svg') as unknown as HTMLElement;
    host.id = 'pk-defs';
    host.setAttribute('class', 'pk-defs');
    host.setAttribute('aria-hidden', 'true');
    host.setAttribute('focusable', 'false');
    const defs = document.createElementNS(NS, 'defs');
    const comet = document.createElementNS(NS, 'g');
    comet.id = ids.cmt;
    const tail = document.createElementNS(NS, 'path');
    tail.setAttribute('d', 'M-6.5 1Q-2.6 16 0 32Q2.6 16 6.5 1Z');
    tail.setAttribute('fill-opacity', '.42');
    const head = document.createElementNS(NS, 'circle');
    head.setAttribute('r', '7');
    comet.append(tail, head);
    defs.append(comet);
    host.append(defs);
    document.body.append(host);
  }
  const defs = host.querySelector('defs')!;
  const add = (id: string, d: string): void => {
    if (document.getElementById(id)) return;
    const p = document.createElementNS(NS, 'path');
    p.id = id;
    p.setAttribute('d', d);
    defs.append(p);
  };
  const corona = coronaFor(shapes, home);
  add(ids.cor.routine, corona.routine);
  add(ids.cor.priority, corona.priority);
  add(ids.cor.immediate, corona.immediate);
  add(ids.cor.flash, corona.flash);
  add(ids.rib, shapes.ribbon);
  return ids;
}

export interface MorphParams {
  state: CharacterState;
  held: ShapeKey | null;
  shapes: PackShapes;
  still: boolean;
  home?: HomeShape;
}

export function bodyMorph(path: SVGPathElement, p: MorphParams): void {
  const { shapes } = p;
  const def = STATES[p.state];
  if (p.still) {
    path.setAttribute('d', shapes.d[def.still ?? heldShape(p.state, p.home)]);
    return;
  }
  const plan = planMorph(p.state, p.held, p.home);
  const end = heldShape(p.state, p.home);
  if (!plan) {
    path.setAttribute('d', shapes.d[end]);
    return;
  }
  const keys = plan.keys;
  const a = document.createElementNS(NS, 'animate');
  a.setAttribute('attributeName', 'd');
  a.setAttribute('dur', `${plan.dur}s`);
  a.setAttribute('begin', 'indefinite');
  a.setAttribute('fill', 'freeze');
  if (shapes.pixel) {
    const vals: string[] = [];
    const ts: string[] = [];
    for (let i = 0; i < keys.length - 1; i++) {
      for (let s = 0; s < 3; s++) {
        vals.push(pixelBlendD(shapes, keys[i]!, keys[i + 1]!, s / 3));
        ts.push((plan.keyTimes[i]! + ((plan.keyTimes[i + 1]! - plan.keyTimes[i]!) * s) / 3).toFixed(3));
      }
    }
    vals.push(shapes.d[keys[keys.length - 1]!]);
    ts.push('1');
    a.setAttribute('calcMode', 'discrete');
    a.setAttribute('values', vals.join(';'));
    a.setAttribute('keyTimes', ts.join(';'));
  } else {
    a.setAttribute('calcMode', 'spline');
    a.setAttribute('values', keys.map((k) => shapes.d[k]).join(';'));
    a.setAttribute('keyTimes', plan.keyTimes.join(';'));
    a.setAttribute('keySplines', plan.keyTimes.slice(1).map(() => plan.spline).join(';'));
  }
  path.setAttribute('d', shapes.d[keys[0]!]);
  path.append(a);
  const begin = (): void => {
    if (!a.isConnected) return;
    try {
      (a as unknown as { beginElement(): void }).beginElement();
      const svg = path.ownerSVGElement;
      if (svg && packClock.isPaused()) svg.pauseAnimations();
    } catch (e) {
      void e;
      path.setAttribute('d', shapes.d[end]);
    }
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(begin);
  else begin();
}
