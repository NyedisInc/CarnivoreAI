/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFrameLoop } from './frame-loop';
import { createItem, paintItem } from './paint';
import { createRectCache } from './rect-cache';
import { makeSpring, stepSpring } from './spring';
import { makeKit, pev } from './motion-test-kit';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  document.body.className = '';
});

function lift(k: ReturnType<typeof makeKit>, id = 'a', x = 10): void {
  k.els.get(id)!.dispatchEvent(pev('pointerdown', x, 25));
  k.move(x + 20);
  k.frames(1);
}

describe('springs, loop and paint', () => {
  it('settles on its target and the loop stops itself', () => {
    const s = makeSpring(0, 'pos');
    s.t = 100;
    let steps = 0;
    while (stepSpring(s, 1 / 60, false) && steps < 2000) steps++;
    expect(s.v).toBe(100);
    expect(s.vel).toBe(0);
    expect(steps).toBeGreaterThan(5);

    const k = makeKit();
    const first = k.adapter.rects;
    k.adapter.rects = () => new Map([...first()].map(([id, r]) => [id, { ...r, y: 80 }]));
    k.handle.sync(false);
    expect(k.handle.stats().running).toBe(true);
    k.rest();
    expect(k.handle.stats().running).toBe(false);
    const frames = k.handle.stats().frames;
    k.frames(10);
    expect(k.handle.stats().frames).toBe(frames);
    expect(k.els.get('a')!.style.transform).toBe('translate3d(0.00px,80.00px,0)');
  });

  it('clamps dt and reports work stats', () => {
    let seen = 0;
    const raf: ((t: number) => void)[] = [];
    const loop = createFrameLoop({ raf: (cb) => raf.push(cb), caf: () => {}, now: () => 0, win: window, doc: document }, (dt) => {
      seen = dt;
      return false;
    });
    loop.wake();
    raf.shift()!(1000);
    loop.wake();
    raf.shift()!(5000);
    expect(seen).toBeCloseTo(1 / 60);
    expect(loop.stats().frames).toBe(2);
  });

  it('writes a style property only when its string changed', () => {
    const el = document.createElement('div');
    const it = createItem('x', el);
    it.x.v = 5;
    paintItem(it);
    el.style.transform = 'translate3d(1px,1px,0)';
    el.style.width = '999px';
    paintItem(it);
    expect(el.style.transform).toBe('translate3d(1px,1px,0)');
    expect(el.style.width).toBe('999px');
    it.x.v = 6;
    paintItem(it);
    expect(el.style.transform).toBe('translate3d(6.00px,0.00px,0)');
    expect(el.style.width).toBe('999px');
  });
});

describe('gesture thresholds', () => {
  it('a mouse needs more than 4 px', () => {
    const k = makeKit();
    const started = vi.fn();
    k.handle.on('dragstart', started);
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(13);
    expect(started).not.toHaveBeenCalled();
    k.move(16);
    expect(started).toHaveBeenCalledTimes(1);
  });

  it('a touch long-press lifts at 320 ms and a 10 px move first cancels it', () => {
    const k = makeKit();
    const started = vi.fn();
    k.handle.on('dragstart', started);
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25, { pointerType: 'touch' }));
    vi.advanceTimersByTime(319);
    expect(started).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(started).toHaveBeenCalledTimes(1);
    window.dispatchEvent(pev('pointerup', 10, 25));
    k.rest();

    const k2 = makeKit();
    const s2 = vi.fn();
    k2.handle.on('dragstart', s2);
    k2.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25, { pointerType: 'touch' }));
    k2.move(22);
    vi.advanceTimersByTime(1000);
    expect(s2).not.toHaveBeenCalled();
  });

  it('a press on a button inside an item does not start a drag, and a disabled core ignores presses', () => {
    const k = makeKit();
    const started = vi.fn();
    k.handle.on('dragstart', started);
    const b = document.createElement('button');
    k.els.get('a')!.appendChild(b);
    b.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(40);
    expect(started).not.toHaveBeenCalled();
    window.dispatchEvent(pev('pointerup', 40, 25));
    k.handle.setEnabled(false);
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(60);
    expect(started).not.toHaveBeenCalled();
  });

  it('a button inside [data-motion-grab] grabs past 4 px and stays a click under it', () => {
    const k = makeKit();
    const started = vi.fn();
    k.handle.on('dragstart', started);
    const b = document.createElement('button');
    b.setAttribute('data-motion-grab', '');
    k.els.get('a')!.appendChild(b);
    b.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(12);
    window.dispatchEvent(pev('pointerup', 12, 25));
    expect(started).not.toHaveBeenCalled();
    b.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(40);
    k.frames(1);
    expect(started).toHaveBeenCalled();
  });

  it('suppresses the click that follows a drag', () => {
    const k = makeKit();
    lift(k);
    window.dispatchEvent(pev('pointerup', 30, 25));
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    k.els.get('a')!.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    vi.advanceTimersByTime(100);
    const later = new MouseEvent('click', { bubbles: true, cancelable: true });
    k.els.get('a')!.dispatchEvent(later);
    expect(later.defaultPrevented).toBe(false);
  });
});

describe('the six endings', () => {
  const endings: [string, (k: ReturnType<typeof makeKit>) => void, boolean][] = [
    ['pointerup', () => window.dispatchEvent(pev('pointerup', 30, 25)), false],
    ['pointercancel', () => window.dispatchEvent(pev('pointercancel', 30, 25)), true],
    ['lost capture', (k) => k.els.get('a')!.dispatchEvent(new Event('lostpointercapture')), true],
    ['escape', () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })), true],
    ['blur', () => window.dispatchEvent(new Event('blur')), true],
    [
      'tab hidden',
      () => {
        Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
      },
      true,
    ],
  ];
  it.each(endings)('%s ends once', (_name, end, cancelled) => {
    const k = makeKit();
    const ended = vi.fn();
    k.handle.on('dragend', ended);
    lift(k);
    end(k);
    expect(ended).toHaveBeenCalledTimes(1);
    expect(ended.mock.calls[0]![0].cancelled).toBe(cancelled);
    expect(k.spies.cancel).toHaveBeenCalledTimes(cancelled ? 1 : 0);
    expect(k.spies.commit).toHaveBeenCalledTimes(cancelled ? 0 : 1);
    end(k);
    expect(ended).toHaveBeenCalledTimes(1);
  });

  it('escape springs every item back to its base rect', () => {
    const k = makeKit();
    lift(k);
    k.move(130);
    k.frames(3);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    k.rest();
    expect(k.els.get('a')!.style.transform).toBe('translate3d(0.00px,0.00px,0)');
    expect(k.els.get('b')!.style.transform).toBe('translate3d(110.00px,0.00px,0)');
    expect(k.getOrder()).toEqual(['a', 'b', 'c']);
  });
});

describe('preview, throttle and settle', () => {
  it('asks the adapter for a preview only when the target key changes', () => {
    const k = makeKit();
    lift(k);
    const after = k.spies.preview.mock.calls.length;
    for (const x of [35, 40, 50, 60]) {
      k.move(x);
      k.frames(1);
    }
    expect(k.spies.preview.mock.calls.length).toBe(after);
    k.move(130);
    k.frames(1);
    expect(k.spies.preview.mock.calls.length).toBe(after + 1);
    expect(k.spies.preview).toHaveBeenLastCalledWith('1');
  });

  it('commits the previewed order once on release', () => {
    const k = makeKit();
    lift(k);
    k.move(130);
    k.frames(2);
    window.dispatchEvent(pev('pointerup', 130, 25));
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
    k.rest();
    expect(k.getOrder()).toEqual(['b', 'a', 'c']);
    expect(k.els.get('a')!.style.transform).toBe('translate3d(110.00px,0.00px,0)');
  });

  it('renders the host at most every 70 ms while the size changes, and once at rest', () => {
    const k = makeKit();
    k.render.mockClear();
    k.els.get('a')!.querySelector('i')!.dispatchEvent(pev('pointerdown', 100, 25));
    for (let i = 0; i < 20; i++) {
      k.move(100 + i * 8);
      k.frames(1);
    }
    const during = k.render.mock.calls.filter((c) => c[0] === 'a');
    expect(during.length).toBeGreaterThan(1);
    expect(during.length).toBeLessThanOrEqual(Math.ceil((20 * 16) / 70) + 1);
    window.dispatchEvent(pev('pointerup', 260, 25));
    k.rest();
    const all = k.render.mock.calls.filter((c) => c[0] === 'a');
    expect(all[all.length - 1]![2]).toBe('settle');
    expect(all[all.length - 1]![1].w).toBe(Math.round(Math.min(300, 100 + 19 * 8)));
  });

  it('holds grid-dragging and the busy flag until the settle finishes', () => {
    const k = makeKit();
    const settled = vi.fn();
    k.handle.on('settle', settled);
    lift(k);
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    expect(k.container.classList.contains('motion-busy')).toBe(true);
    expect(k.handle.isBusy()).toBe(true);
    window.dispatchEvent(pev('pointerup', 130, 25));
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    expect(k.handle.isBusy()).toBe(true);
    k.frames(1);
    expect(settled).not.toHaveBeenCalled();
    k.rest();
    expect(settled).toHaveBeenCalledTimes(1);
    expect(document.body.classList.contains('grid-dragging')).toBe(false);
    expect(k.container.classList.contains('motion-busy')).toBe(false);
    expect(k.handle.isBusy()).toBe(false);
    expect(k.els.get('a')!.classList.contains('motion-lifted')).toBe(false);
  });

  it('reduced motion snaps and drops the tilt', () => {
    const k = makeKit({ reduced: () => true });
    lift(k);
    expect(k.els.get('a')!.style.transform).not.toContain('rotate');
    k.move(130);
    k.frames(1);
    window.dispatchEvent(pev('pointerup', 130, 25));
    k.frames(2);
    expect(k.handle.isBusy()).toBe(false);
    expect(k.els.get('a')!.style.transform).toBe('translate3d(110.00px,0.00px,0)');
  });

  it('lifts with a tilt, scale and reduced opacity', () => {
    const k = makeKit();
    lift(k);
    k.frames(30);
    const el = k.els.get('a')!;
    expect(el.classList.contains('motion-lifted')).toBe(true);
    expect(el.style.transform).toContain('rotate(');
    expect(el.style.transform).toContain('scale(1.03');
    expect(Number(el.style.opacity)).toBeCloseTo(0.86, 1);
  });
});

describe('keyboard and external entry', () => {
  it('steps with arrows, resizes with shift, reverts on escape and ends on enter', () => {
    const k = makeKit();
    const a = k.els.get('a')!;
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
    expect(k.spies.step).toHaveBeenLastCalledWith('a', { dir: 'right', resize: false });
    expect(k.spies.begin).toHaveBeenCalledTimes(1);
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true, cancelable: true }));
    expect(k.spies.step).toHaveBeenLastCalledWith('a', { dir: 'right', resize: true });
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(k.spies.cancel).toHaveBeenCalledTimes(1);
    k.rest();
    expect(a.style.transform).toBe('translate3d(0.00px,0.00px,0)');
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(k.spies.cancel).toHaveBeenCalledTimes(1);
  });

  it('leaves a plain arrow on a tab button to the tablist and lets a Shift arrow start the cell session', () => {
    const k = makeKit();
    const a = k.els.get('a')!;
    const tab = document.createElement('button');
    tab.setAttribute('role', 'tab');
    tab.setAttribute('data-motion-handle', '');
    a.appendChild(tab);
    tab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
    expect(k.spies.step).not.toHaveBeenCalled();
    expect(k.spies.begin).not.toHaveBeenCalled();
    tab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true, cancelable: true }));
    expect(k.spies.step).toHaveBeenLastCalledWith('a', { dir: 'right', resize: true });
  });

  it('takes a drag that started outside and commits it on release', () => {
    const k = makeKit();
    const el = document.createElement('div');
    el.dataset.id = 'n';
    k.container.appendChild(el);
    k.handle.register('n', el);
    const ok = k.handle.beginExternal({ id: 'n', rect: { x: 0, y: 0, w: 100, h: 50 }, grab: { x: 10, y: 10 } }, pev('pointerdown', 120, 40));
    expect(ok).toBe(true);
    k.move(130);
    k.frames(2);
    window.dispatchEvent(pev('pointerup', 130, 40));
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
    k.rest();
    expect(k.handle.isBusy()).toBe(false);
  });
});

describe('rect cache', () => {
  it('measures once per gesture and again after a scroll', () => {
    const el = document.createElement('div');
    const spy = vi.spyOn(el, 'getBoundingClientRect');
    const cache = createRectCache(el, window);
    cache.get();
    cache.get();
    expect(spy).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event('scroll'));
    cache.get();
    expect(spy).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event('resize'));
    cache.get();
    expect(spy).toHaveBeenCalledTimes(3);
    cache.dispose();
    window.dispatchEvent(new Event('scroll'));
    cache.get();
    expect(spy).toHaveBeenCalledTimes(3);
  });
});
