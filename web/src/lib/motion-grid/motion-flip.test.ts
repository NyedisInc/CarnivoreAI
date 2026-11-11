/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeKit, pev } from './motion-test-kit';
import type { Target } from './types';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  document.body.className = '';
});

type Kit = ReturnType<typeof makeKit>;

function countSizeWrites(el: HTMLElement): { n: () => number; reset: () => void } {
  let n = 0;
  for (const prop of ['width', 'height'] as const) {
    const proto = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el.style), prop)!;
    Object.defineProperty(el.style, prop, {
      configurable: true,
      get: () => proto.get!.call(el.style),
      set: (v: string) => {
        n++;
        proto.set!.call(el.style, v);
      },
    });
  }
  return { n: () => n, reset: () => (n = 0) };
}

function narrowNeighbours(k: Kit, mark?: (key: string) => Target['mark']): void {
  const orig = k.adapter.preview.bind(k.adapter);
  k.adapter.preview = (g, key) => {
    const t = orig(g, key);
    const rects = new Map(t.rects);
    for (const [id, r] of rects) if (id !== 'a') rects.set(id, { ...r, w: 60 });
    return { ...t, rects, mark: mark?.(key) };
  };
}

function lift(k: Kit, id = 'a', x = 10): void {
  k.els.get(id)!.dispatchEvent(pev('pointerdown', x, 25));
  k.move(x + 20);
  k.frames(1);
}

describe("sizePaint 'flip'", () => {
  it('writes no size and no render while size springs move, one of each at rest, and the final render lands before the settle', () => {
    const k = makeKit({ autoscroll: false, sizePaint: 'flip' });
    narrowNeighbours(k);
    const b = k.els.get('b')!;
    expect(b.style.transformOrigin).toBe('0 0');
    k.render.mockClear();
    const w = countSizeWrites(b);
    const events: string[] = [];
    k.handle.on('settle', () => events.push(`settle:${document.body.classList.contains('grid-dragging')}`));
    k.render.mockImplementation((id: string, size: { w: number }) => {
      if (id === 'b') events.push(`render:${size.w}`);
    });
    lift(k);
    k.move(130);
    k.frames(1);
    expect(b.style.width).toBe('100px');
    expect(b.style.transform).toMatch(/scale\(0\.\d+,/);
    expect(w.n()).toBe(0);
    expect(events).toEqual([]);
    k.frames(80);
    expect(w.n()).toBe(1);
    expect(b.style.width).toBe('60px');
    expect(b.style.transform).not.toMatch(/scale\(0\.\d+,/);
    expect(events).toEqual(['render:60']);
    window.dispatchEvent(pev('pointerup', 130, 25));
    k.rest();
    expect(events).toEqual(['render:60', 'settle:false']);
    expect(w.n()).toBe(1);
  });

  it('default options keep the per-frame size writes and throttled renders', () => {
    const k = makeKit({ autoscroll: false });
    narrowNeighbours(k);
    const b = k.els.get('b')!;
    const w = countSizeWrites(b);
    lift(k);
    k.move(130);
    k.frames(3);
    expect(w.n()).toBeGreaterThan(1);
    expect(b.style.transformOrigin).toBe('');
  });

  it('folds the lift scale into the translate (origin stays 0 0)', () => {
    const k = makeKit({ autoscroll: false, sizePaint: 'flip' });
    const a = k.els.get('a')!;
    lift(k, 'a', 10);
    k.frames(60);
    expect(a.style.transformOrigin).toBe('0 0');
    const m = a.style.transform.match(/translate3d\(([-\d.]+)px,([-\d.]+)px,0\) rotate\(([-\d.]+)deg\) scale\(1\.0300\)/);
    expect(m).not.toBeNull();
  });
});

describe('lift option', () => {
  it('tilt false keeps rotation 0 and the scale is the thumbnail fit', () => {
    const k = makeKit({ autoscroll: false, lift: { tilt: false, maxW: 50, maxH: 400 } });
    const a = k.els.get('a')!;
    lift(k);
    k.move(200);
    k.frames(80);
    expect(a.style.transform).not.toContain('rotate');
    expect(a.style.transform).toContain('scale(0.5000)');
  });

  it('without it the velocity tilt and 1.03 stay', () => {
    const k = makeKit({ autoscroll: false });
    const a = k.els.get('a')!;
    lift(k);
    k.frames(60);
    expect(a.style.transform).toContain('rotate');
    expect(a.style.transform).toContain('scale(1.0300)');
  });
});

describe('Target.mark', () => {
  it('writes data-label and data-kind, jumps on a key change and keeps full opacity once visible', () => {
    const k = makeKit({ autoscroll: false });
    narrowNeighbours(k, (key) => ({ label: `to ${key}`, kind: key === '2' ? 'tab' : 'column' }));
    const landing = k.container.querySelector<HTMLElement>('.motion-landing')!;
    lift(k);
    k.frames(60);
    expect(landing.dataset.label).toBe('to 0');
    expect(landing.dataset.kind).toBe('column');
    expect(landing.style.opacity).toBe('1');
    k.move(130);
    k.frames(1);
    expect(landing.dataset.label).toBe('to 1');
    expect(landing.style.opacity).toBe('1');
    expect(landing.style.transform).toBe('translate3d(110.00px,0.00px,0)');
    k.move(250);
    k.frames(1);
    expect(landing.dataset.kind).toBe('tab');
    window.dispatchEvent(pev('pointerup', 250, 25));
    k.rest();
    lift(k, 'a', 10);
    expect(landing.dataset.label).toBe('to 0');
  });

  it('a surface that never marks leaves the landing bare', () => {
    const k = makeKit({ autoscroll: false });
    const landing = k.container.querySelector<HTMLElement>('.motion-landing')!;
    lift(k);
    expect(landing.hasAttribute('data-label')).toBe(false);
    expect(landing.hasAttribute('data-kind')).toBe(false);
  });
});

describe('beginExternal', () => {
  it("as 'move' lifts a placed item and a cancel springs it home at full opacity", () => {
    const k = makeKit({ autoscroll: false });
    const a = k.els.get('a')!;
    const ok = k.handle.beginExternal({ id: 'a', rect: { x: 0, y: 0, w: 1, h: 1 }, grab: { x: 0, y: 0 } }, pev('pointerdown', 30, 25), { as: 'move' });
    expect(ok).toBe(true);
    expect(a.classList.contains('motion-lifted')).toBe(true);
    k.move(250);
    k.frames(20);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    k.rest();
    expect(k.spies.cancel).toHaveBeenCalledTimes(1);
    expect(a.style.transform).toBe('translate3d(0.00px,0.00px,0)');
    expect(a.style.opacity).toBe('');
  });

  it('leaveOnDrop fades the item on a committed drop', () => {
    const k = makeKit({ autoscroll: false });
    const a = k.els.get('a')!;
    k.handle.beginExternal({ id: 'a', rect: { x: 0, y: 0, w: 1, h: 1 }, grab: { x: 0, y: 0 } }, pev('pointerdown', 30, 25), { as: 'move', leaveOnDrop: true });
    k.move(130);
    k.frames(3);
    window.dispatchEvent(pev('pointerup', 130, 25));
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
    k.rest();
    expect(a.style.opacity).toBe('0');
  });
});
