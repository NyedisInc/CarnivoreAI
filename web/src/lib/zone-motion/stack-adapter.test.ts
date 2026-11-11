/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountMotion } from '../motion-grid';
import { pev } from '../motion-grid/motion-test-kit';
import type { Env, MotionHandle } from '../motion-grid/types';
import { createStackAdapter, STACK_ID_ATTR, STACK_RESIZE_ATTR, type StackItem } from './stack-adapter';

let clock = 0;
const queue: ((t: number) => void)[] = [];

/** Run `n` frames of 16 ms on the fake clock. */
function frames(n: number): void {
  for (let i = 0; i < n; i++) {
    clock += 16;
    queue.splice(0).forEach((cb) => cb(clock));
  }
}

function column() {
  let items: StackItem[] = [{ id: 'a', w: 0, h: 40 }, { id: 'b', w: 0, h: 60 }, { id: 'c', w: 0, h: 40 }];
  const place = vi.fn((id: string, index: number) => {
    const rest = items.filter((i) => i.id !== id);
    rest.splice(index, 0, items.find((i) => i.id === id)!);
    items = rest;
  });
  const resize = vi.fn((id: string, h: number) => {
    items = items.map((i) => (i.id === id ? { ...i, h } : i));
  });
  const adapter = createStackAdapter({
    axis: 'y', items: () => items, width: () => 400, place,
    resize: { limits: () => ({ min: 30, max: 100 }), commit: resize },
    grab: '[data-grab]',
  });
  const env: Env = { raf: (cb) => queue.push(cb), caf: () => {}, now: () => clock, win: window, doc: document };
  const container = document.createElement('div');
  document.body.appendChild(container);
  container.getBoundingClientRect = () => ({ left: 0, top: 0, right: 400, bottom: 300, width: 400, height: 300, x: 0, y: 0, toJSON() {} }) as DOMRect;
  const handle: MotionHandle = mountMotion(container, adapter, { env, translate: (k) => k });
  const els = new Map<string, HTMLElement>();
  for (const it of items) {
    const el = document.createElement('div');
    el.setAttribute(STACK_ID_ATTR, it.id);
    el.tabIndex = 0;
    el.innerHTML = '<i data-grab="1"><button>x</button></i><b ' + STACK_RESIZE_ATTR + '></b>';
    container.appendChild(el);
    els.set(it.id, el);
    handle.register(it.id, el);
  }
  handle.sync(true);
  frames(2);
  return { handle, els, place, resize, order: () => items.map((i) => i.id), adapter };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  document.body.className = '';
});

describe('stack adapter', () => {
  it('lays the column out one after another', () => {
    const k = column();
    expect([...k.adapter.rects().values()].map((r) => r.y)).toEqual([0, 40, 100]);
  });

  it('reorders by insertion index and writes once on release', () => {
    const k = column();
    const grip = k.els.get('a')!.querySelector('i')!;
    grip.dispatchEvent(pev('pointerdown', 10, 10));
    window.dispatchEvent(pev('pointermove', 12, 90));
    frames(2);
    window.dispatchEvent(pev('pointermove', 12, 140));
    frames(2);
    window.dispatchEvent(pev('pointerup', 12, 140));
    frames(60);
    expect(k.place).toHaveBeenCalledTimes(1);
    expect(k.place).toHaveBeenCalledWith('a', 2, false);
    expect(k.order()).toEqual(['b', 'c', 'a']);
  });

  it('a press on a button inside the grab region stays a click', () => {
    const k = column();
    const started = vi.fn();
    k.handle.on('dragstart', started);
    k.els.get('a')!.querySelector('button')!.dispatchEvent(pev('pointerdown', 10, 10));
    window.dispatchEvent(pev('pointermove', 12, 140));
    expect(started).not.toHaveBeenCalled();
  });

  it('a press outside the grab region grabs nothing', () => {
    const k = column();
    expect(k.adapter.hit(k.els.get('b')!, pev('pointerdown', 1, 1))).toBeNull();
  });

  it('cancel writes nothing and a drop outside the container cancels', () => {
    const k = column();
    k.els.get('a')!.querySelector('i')!.dispatchEvent(pev('pointerdown', 10, 10));
    window.dispatchEvent(pev('pointermove', 12, 90));
    frames(2);
    window.dispatchEvent(pev('pointermove', 12, 900));
    frames(2);
    window.dispatchEvent(pev('pointerup', 12, 900));
    frames(60);
    expect(k.place).not.toHaveBeenCalled();
    expect(k.order()).toEqual(['a', 'b', 'c']);
  });

  it('resizes from the bottom edge, clamped, with one write', () => {
    const k = column();
    k.els.get('a')!.querySelector('b')!.dispatchEvent(pev('pointerdown', 10, 40));
    window.dispatchEvent(pev('pointermove', 10, 80));
    frames(2);
    window.dispatchEvent(pev('pointermove', 10, 400));
    frames(2);
    window.dispatchEvent(pev('pointerup', 10, 400));
    frames(60);
    expect(k.resize).toHaveBeenCalledTimes(1);
    expect(k.resize).toHaveBeenCalledWith('a', 100);
  });

  it('a grow follows the pointer even when the container moves under it mid-gesture', () => {
    const k = column();
    const box = k.els.get('a')!.parentElement!;
    let top = 0;
    box.getBoundingClientRect = () => ({ left: 0, top, right: 400, bottom: 300 + top, width: 400, height: 300, x: 0, y: top, toJSON() {} }) as DOMRect;
    k.els.get('a')!.querySelector('b')!.dispatchEvent(pev('pointerdown', 10, 40));
    for (const dy of [4, 8, 12, 16]) {
      top -= dy;
      window.dispatchEvent(pev('pointermove', 10, 40 + dy));
      frames(2);
    }
    window.dispatchEvent(pev('pointerup', 10, 56));
    frames(60);
    expect(k.resize).toHaveBeenCalledTimes(1);
    expect(k.resize).toHaveBeenCalledWith('a', 56);
  });

  it('keyboard: arrows only preview; Escape writes nothing, Enter writes once with the last place or size', () => {
    let k = column();
    for (let i = 0; i < 2; i++) k.els.get('a')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    k.els.get('a')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(k.place).not.toHaveBeenCalled();
    expect(k.order()).toEqual(['a', 'b', 'c']);
    for (let i = 0; i < 2; i++) k.els.get('a')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    k.els.get('a')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(k.place).toHaveBeenCalledExactlyOnceWith('a', 2, false);
    expect(k.order()).toEqual(['b', 'c', 'a']);
    k = column();
    const a = k.els.get('a')!;
    for (let i = 0; i < 3; i++) a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true }));
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(k.resize).not.toHaveBeenCalled();
    for (let i = 0; i < 3; i++) a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true }));
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(k.resize).toHaveBeenCalledExactlyOnceWith('a', 88);
    a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(k.place).not.toHaveBeenCalled();
  });

  it('keyboard: a mixed move and resize session writes both on Enter and nothing on Escape', () => {
    const press = (k: ReturnType<typeof column>, key: string, shiftKey = false): void => {
      k.els.get('a')!.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
    };
    let k = column();
    press(k, 'ArrowDown');
    press(k, 'ArrowDown', true);
    press(k, 'Enter');
    expect(k.place).toHaveBeenCalledExactlyOnceWith('a', 1, false);
    expect(k.resize).toHaveBeenCalledExactlyOnceWith('a', 56);
    k = column();
    press(k, 'ArrowDown', true);
    press(k, 'ArrowDown');
    press(k, 'Enter');
    expect(k.place).toHaveBeenCalledExactlyOnceWith('a', 1, false);
    expect(k.resize).toHaveBeenCalledExactlyOnceWith('a', 56);
    k = column();
    press(k, 'ArrowDown');
    press(k, 'ArrowDown', true);
    press(k, 'Escape');
    expect(k.place).not.toHaveBeenCalled();
    expect(k.resize).not.toHaveBeenCalled();
  });
});
