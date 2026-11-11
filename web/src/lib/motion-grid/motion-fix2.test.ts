/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { acquireDragHold } from './drag-hold';
import { makeKit, pev } from './motion-test-kit';
import type { ItemId, Target } from './types';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  document.body.className = '';
});

const key = (el: Element, k: string, init: KeyboardEventInit = {}): void => {
  el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init }));
};

describe('drag hold', () => {
  it('keeps the class while any holder holds, and a double release counts once', () => {
    const a = acquireDragHold(document);
    const b = acquireDragHold(document);
    a();
    a();
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    b();
    expect(document.body.classList.contains('grid-dragging')).toBe(false);
  });

  it('a core settling does not drop another holder', () => {
    const k = makeKit();
    const other = acquireDragHold(document);
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(30);
    k.frames(1);
    window.dispatchEvent(pev('pointerup', 130, 25));
    k.rest();
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    other();
    expect(document.body.classList.contains('grid-dragging')).toBe(false);
  });
});

describe('carry hold (the drawer duck, #2936)', () => {
  const on = (c: string): boolean => document.body.classList.contains(c);

  it('grid-carrying is on from lift and off at pointer release while grid-dragging lasts through the settle', () => {
    const k = makeKit();
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(30);
    k.frames(1);
    expect(on('grid-carrying')).toBe(true);
    window.dispatchEvent(pev('pointerup', 130, 25));
    expect(on('grid-carrying')).toBe(false);
    expect(on('grid-dragging')).toBe(true);
    k.rest();
    expect(on('grid-dragging')).toBe(false);
  });

  it('Escape drops grid-carrying at once too', () => {
    const k = makeKit();
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(30);
    k.frames(1);
    key(document.body, 'Escape');
    expect(on('grid-carrying')).toBe(false);
    k.rest();
  });
});

describe('release before the first frame', () => {
  it('cancels through the adapter when there is no target', () => {
    const k = makeKit();
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(30);
    window.dispatchEvent(pev('pointerup', 30, 25));
    expect(k.spies.begin).toHaveBeenCalledTimes(1);
    expect(k.spies.cancel).toHaveBeenCalledTimes(1);
    expect(k.spies.commit).not.toHaveBeenCalled();
    k.rest();
    expect(k.handle.isBusy()).toBe(false);
  });
});

describe('keyboard session', () => {
  function previewKit() {
    const k = makeKit();
    k.adapter.stepFromTarget = true;
    k.adapter.step = (id: ItemId, s, from?: Target | null) => {
      const order = (from?.payload as ItemId[] | undefined) ?? k.getOrder();
      const i = order.indexOf(id);
      const j = s.dir === 'right' ? i + 1 : i - 1;
      if (j < 0 || j > 2) return null;
      const next = [...order];
      next.splice(i, 1);
      next.splice(j, 0, id);
      return { key: `k${next.join('')}`, rects: new Map(next.map((n, x) => [n, { x: x * 110, y: 0, w: 100, h: 50 }])), payload: next };
    };
    return k;
  }

  it('previews each step and writes once when Enter ends it', () => {
    const k = previewKit();
    const a = k.els.get('a')!;
    key(a, 'ArrowRight');
    key(a, 'ArrowRight');
    expect(k.spies.commit).not.toHaveBeenCalled();
    key(a, 'Enter');
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
    expect(k.getOrder()).toEqual(['b', 'c', 'a']);
  });

  it('writes once when focus leaves the item', () => {
    const k = previewKit();
    const a = k.els.get('a')!;
    key(a, 'ArrowRight');
    a.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
  });

  it('drops a session whose item is unregistered: no write on a later key or focusout', () => {
    const k = previewKit();
    const a = k.els.get('a')!;
    const b = k.els.get('b')!;
    const before = b.style.transform;
    key(a, 'ArrowRight');
    k.rest();
    expect(b.style.transform).not.toBe(before);
    k.handle.unregister('a');
    k.rest();
    expect(b.style.transform).toBe(before);
    key(b, 'Enter');
    b.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
    a.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
    expect(k.spies.commit).not.toHaveBeenCalled();
  });

  it('keeps the session when an unrelated item is unregistered', () => {
    const k = previewKit();
    const a = k.els.get('a')!;
    key(a, 'ArrowRight');
    k.handle.unregister('c');
    key(a, 'Enter');
    expect(k.spies.commit).toHaveBeenCalledTimes(1);
  });

  it('Escape writes nothing and restores the entry state', () => {
    const k = previewKit();
    const a = k.els.get('a')!;
    key(a, 'ArrowRight');
    key(a, 'Escape');
    expect(k.spies.commit).not.toHaveBeenCalled();
    expect(k.spies.cancel).toHaveBeenCalledTimes(1);
    expect(k.getOrder()).toEqual(['a', 'b', 'c']);
  });
});

describe('extent and grab guards', () => {
  it('releases the pinned height when the adapter stops asking for one', () => {
    const k = makeKit();
    let h: number | null = 300;
    k.adapter.extent = () => h;
    k.handle.sync(true);
    k.frames(2);
    expect(k.container.style.height).toBe('300px');
    h = null;
    k.handle.sync(true);
    expect(k.container.style.height).toBe('');
  });

  it('a press inside a dialog does not lift', () => {
    const k = makeKit();
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    k.els.get('a')!.appendChild(dialog);
    const started = vi.fn();
    k.handle.on('dragstart', started);
    dialog.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(40);
    expect(started).not.toHaveBeenCalled();
  });
});

describe('gesture coordinates', () => {
  it('delta is pixel exact on a surface offset from the page origin', () => {
    const k = makeKit();
    k.container.getBoundingClientRect = () =>
      ({ left: 322, top: 2, right: 722, bottom: 202, width: 400, height: 200, x: 322, y: 2, toJSON() {} }) as DOMRect;
    let seen = { x: 0, y: 0 };
    const key0 = k.adapter.targetKey;
    k.adapter.targetKey = function (g) {
      seen = g.delta;
      return key0.call(this, g);
    };
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 332, 27));
    k.move(409, 27);
    k.frames(1);
    expect(seen).toEqual({ x: 77, y: 0 });
    expect(seen.x).toBe(409 - 332);
  });
});

describe('landing box and frame reads', () => {
  it('keeps the landing box visible at rest during a drag', () => {
    const k = makeKit();
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 25));
    k.move(150);
    k.frames(60);
    const landing = k.container.querySelector<HTMLElement>('.motion-landing')!;
    expect(landing.style.opacity).toBe('1');
  });

  it('reads no layout inside the frame loop once the gesture began', () => {
    const k = makeKit();
    const spy = vi.spyOn(k.container, 'getBoundingClientRect');
    k.els.get('a')!.dispatchEvent(pev('pointerdown', 10, 300));
    k.move(40, 300);
    k.frames(1);
    const after = spy.mock.calls.length;
    k.move(150, 300);
    k.frames(20);
    expect(spy.mock.calls.length).toBe(after);
  });
});
