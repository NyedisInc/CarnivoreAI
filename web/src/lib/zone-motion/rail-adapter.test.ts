/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountMotion } from '../motion-grid';
import { pev } from '../motion-grid/motion-test-kit';
import type { Env, MotionHandle } from '../motion-grid/types';
import { STACK_ID_ATTR } from './stack-adapter';
import { aimRail, createRailAdapter, layoutRail, RAIL_PENDING, type RailAcross, type RailGeometry } from './rail-adapter';

let clock = 0;
const queue: ((t: number) => void)[] = [];

/** Run `n` frames of 16 ms on the fake clock. */
function frames(n: number): void {
  for (let i = 0; i < n; i++) {
    clock += 16;
    queue.splice(0).forEach((cb) => cb(clock));
  }
}

const GEO: RailGeometry = { axis: 'y', length: 400, cross: 36, pad: 4, gap: 2 };
const SIZE = (): { w: number; h: number } => ({ w: 28, h: 28 });

function bar(over: { split?: boolean; across?: RailAcross | null } = {}) {
  let sections: string[][] = [['a', 'b'], ['c']];
  let pending = false;
  const place = vi.fn();
  const leave = vi.fn();
  const onAim = vi.fn();
  const onEnd = vi.fn();
  const onLift = vi.fn();
  const adapter = createRailAdapter({
    sections: () => (pending ? [sections[0]!, [...sections[1]!, RAIL_PENDING]] : sections),
    cuts: () => [0.5],
    size: SIZE,
    geometry: () => GEO,
    canSplit: () => over.split ?? false,
    origin: () => ({ x: 0, y: 0 }),
    across: () => over.across ?? null,
    place, leave, onLift, onAim, onEnd,
  });
  const env: Env = { raf: (cb) => queue.push(cb), caf: () => {}, now: () => clock, win: window, doc: document };
  const container = document.createElement('div');
  document.body.appendChild(container);
  container.getBoundingClientRect = () => ({ left: 0, top: 0, right: 36, bottom: 400, width: 36, height: 400, x: 0, y: 0, toJSON() {} }) as DOMRect;
  const handle: MotionHandle = mountMotion(container, adapter, { env, translate: (k) => k, autoscroll: false });
  const els = new Map<string, HTMLElement>();
  const add = (id: string): HTMLElement => {
    const el = document.createElement('div');
    el.setAttribute(STACK_ID_ATTR, id);
    el.tabIndex = 0;
    container.appendChild(el);
    els.set(id, el);
    handle.register(id, el);
    return el;
  };
  for (const id of ['a', 'b', 'c']) add(id);
  handle.sync(true);
  frames(2);
  return { handle, els, container, place, leave, onAim, onEnd, onLift, add, setPending: (on: boolean) => (pending = on), adapter };
}

function carry(k: ReturnType<typeof bar>, id: string, x: number, y: number): void {
  k.els.get(id)!.dispatchEvent(pev('pointerdown', 10, 10));
  window.dispatchEvent(pev('pointermove', 12, 20));
  frames(2);
  window.dispatchEvent(pev('pointermove', x, y));
  frames(3);
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  document.body.className = '';
});

describe('rail geometry', () => {
  it('lays each section from the start of its share of the strip, keys centered across', () => {
    const rects = layoutRail([['a', 'b'], ['c']], [0.5], SIZE, GEO);
    expect(rects.get('a')).toEqual({ x: 4, y: 4, w: 28, h: 28 });
    expect(rects.get('b')).toEqual({ x: 4, y: 34, w: 28, h: 28 });
    expect(rects.get('c')).toEqual({ x: 4, y: 204, w: 28, h: 28 });
  });

  it('runs along x for a bottom bar', () => {
    expect(layoutRail([['a', 'b']], [], SIZE, { ...GEO, axis: 'x', length: 300, cross: 40 }).get('b')).toEqual({ x: 34, y: 6, w: 28, h: 28 });
  });

  it('aims at a section and an insertion index, and offers the split only where the keys leave room', () => {
    const rects = layoutRail([['a', 'b'], ['c']], [0.5], SIZE, GEO);
    const aim = (pos: number, skip: string | null, can: boolean) => aimRail([['a', 'b'], ['c']], [0.5], rects, 400, 'y', pos, skip, () => can);
    expect(aim(60, 'a', false)).toEqual({ section: 0, index: 1, split: false, offer: null });
    expect(aim(250, 'a', false)).toMatchObject({ section: 1, index: 1 });
    expect(aim(330, 'a', true)).toEqual({ section: 1, index: 0, split: true, offer: 1 });
  });
});

describe('rail adapter on the core', () => {
  it('reorders inside a section: the keys glide, the landing box shows, one write on release', () => {
    const k = bar();
    carry(k, 'a', 12, 60);
    expect(k.onLift).toHaveBeenCalledWith('a');
    const landing = k.container.querySelector<HTMLElement>('.motion-landing')!;
    expect(Number(landing.style.opacity || 1)).toBeGreaterThan(0);
    expect(k.els.get('b')!.style.transform).toContain('4.00px');
    window.dispatchEvent(pev('pointerup', 12, 60));
    frames(60);
    expect(k.place).toHaveBeenCalledTimes(1);
    expect(k.place).toHaveBeenCalledWith('a', { section: 0, index: 1, split: false }, false);
    expect(k.onEnd).toHaveBeenCalled();
  });

  it('dropping a key where it already sits writes nothing', () => {
    const k = bar();
    carry(k, 'a', 12, 22);
    window.dispatchEvent(pev('pointerup', 12, 22));
    frames(60);
    expect(k.place).not.toHaveBeenCalled();
  });

  it('moves a key into another section', () => {
    const k = bar();
    carry(k, 'a', 12, 250);
    window.dispatchEvent(pev('pointerup', 12, 250));
    frames(60);
    expect(k.place).toHaveBeenCalledWith('a', { section: 1, index: 1, split: false }, false);
  });

  it('the far end of a splittable section takes the key into a NEW section, and the aim says so', () => {
    const k = bar({ split: true });
    carry(k, 'a', 12, 330);
    expect(k.onAim).toHaveBeenLastCalledWith({ section: 1, index: null, offer: 1, onBox: true, across: null });
    window.dispatchEvent(pev('pointerup', 12, 330));
    frames(60);
    expect(k.place).toHaveBeenCalledWith('a', { section: 1, index: 0, split: true }, false);
  });

  it('past the strip it lands on the other bar when one is under the pointer, else it leaves, once either way', () => {
    const across: RailAcross = { edge: 'bottom', spot: { section: 0, index: 2, split: false }, offer: null };
    const k = bar({ across });
    carry(k, 'a', 200, 60);
    expect(k.onAim).toHaveBeenLastCalledWith({ section: null, index: null, offer: null, onBox: false, across });
    window.dispatchEvent(pev('pointerup', 200, 60));
    frames(60);
    expect(k.leave).toHaveBeenCalledTimes(1);
    expect(k.leave).toHaveBeenCalledWith('a', across);
    expect(k.place).not.toHaveBeenCalled();

    const off = bar();
    carry(off, 'b', 200, 60);
    window.dispatchEvent(pev('pointerup', 200, 60));
    frames(60);
    expect(off.leave).toHaveBeenCalledWith('b', null);
  });

  it('a key dropped on the other bars split box is told to split it, once', () => {
    const across: RailAcross = { edge: 'bottom', spot: { section: 1, index: 0, split: true }, offer: 1 };
    const k = bar({ across });
    carry(k, 'a', 200, 60);
    expect(k.onAim).toHaveBeenLastCalledWith({ section: null, index: null, offer: null, onBox: false, across });
    window.dispatchEvent(pev('pointerup', 200, 60));
    frames(60);
    expect(k.leave).toHaveBeenCalledTimes(1);
    expect(k.leave).toHaveBeenCalledWith('a', across);
  });

  it('a drag in a scrolled strip lands under the pointer, scrolled before the press or during the drag', () => {
    const before = bar();
    before.container.scrollTop = 100;
    carry(before, 'a', 12, 150);
    window.dispatchEvent(pev('pointerup', 12, 150));
    frames(60);
    expect(before.place).toHaveBeenCalledWith('a', { section: 1, index: 1, split: false }, false);

    const during = bar();
    carry(during, 'a', 12, 150);
    during.container.scrollTop = 100;
    window.dispatchEvent(pev('pointermove', 12, 151));
    frames(3);
    window.dispatchEvent(pev('pointerup', 12, 151));
    frames(60);
    expect(during.place).toHaveBeenCalledWith('a', { section: 1, index: 1, split: false }, false);
  });

  it('a press on a button inside a grab region clicks under 4 px and drags past it', () => {
    const k = bar();
    const el = k.els.get('a')!;
    el.setAttribute('data-motion-grab', '');
    const button = document.createElement('button');
    el.appendChild(button);
    const click = vi.fn();
    button.addEventListener('click', click);
    button.dispatchEvent(pev('pointerdown', 10, 10));
    window.dispatchEvent(pev('pointermove', 11, 12));
    window.dispatchEvent(pev('pointerup', 11, 12));
    frames(2);
    expect(k.onLift).not.toHaveBeenCalled();
    button.dispatchEvent(pev('pointerdown', 10, 10));
    window.dispatchEvent(pev('pointermove', 12, 40));
    frames(2);
    expect(k.onLift).toHaveBeenCalledWith('a');
    window.dispatchEvent(pev('pointerup', 12, 40));
    frames(60);
  });

  it('Escape in the air writes nothing and the keys spring home', () => {
    const k = bar();
    carry(k, 'a', 12, 250);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    frames(60);
    expect(k.place).not.toHaveBeenCalled();
    expect(k.leave).not.toHaveBeenCalled();
    expect(k.onEnd).toHaveBeenCalled();
    expect(k.els.get('a')!.style.transform).toContain('4.00px,4.00px');
  });

  it('a widget dragged in from the drawer lands once, as an external placement', () => {
    const k = bar();
    k.setPending(true);
    const pending = k.add(RAIL_PENDING);
    const taken = k.handle.beginExternal({ id: RAIL_PENDING, rect: { x: 0, y: 0, w: 28, h: 28 }, grab: { x: 14, y: 14 } }, pev('pointerdown', 10, 60));
    expect(taken).toBe(true);
    window.dispatchEvent(pev('pointermove', 12, 60));
    frames(3);
    window.dispatchEvent(pev('pointerup', 12, 60));
    frames(60);
    expect(pending.isConnected).toBe(true);
    expect(k.place).toHaveBeenCalledTimes(1);
    expect(k.place).toHaveBeenCalledWith(RAIL_PENDING, { section: 0, index: 2, split: false }, true);
  });

  it('keyboard: arrows only preview; Escape writes nothing, Enter writes once at the last place; resize is refused', () => {
    const k = bar();
    const a = k.els.get('a')!;
    a.focus();
    const press = (key: string, init: KeyboardEventInit = {}): boolean => a.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }));
    press('ArrowDown');
    press('Escape');
    expect(k.place).not.toHaveBeenCalled();
    press('ArrowDown');
    press('ArrowDown');
    press('ArrowDown');
    press('ArrowDown', { shiftKey: true });
    press('Enter');
    expect(k.place).toHaveBeenCalledExactlyOnceWith('a', { section: 0, index: 1, split: false }, false);
  });
});
