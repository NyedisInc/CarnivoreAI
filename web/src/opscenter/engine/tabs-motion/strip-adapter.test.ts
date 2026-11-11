/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import type { Rect } from '../../../lib/motion-grid';
import { mountKeyboard } from '../../../lib/motion-grid/motion-test-kit';
import { createStripAdapter, flow, insertionIndex } from './strip-adapter';

const rect = (x: number, w = 100): Rect => ({ x, y: 0, w, h: 30 });
const measured = new Map<string, Rect>([['a', rect(0)], ['b', rect(101)], ['c', rect(202)]]);

test('flow lays tabs out left to right in the given order, keeping widths and gaps', () => {
  const out = flow(['c', 'a', 'b'], measured, 1);
  expect(out.get('c')!.x).toBe(0);
  expect(out.get('a')!.x).toBe(101);
  expect(out.get('b')!.x).toBe(202);
});

test('insertionIndex counts the other tabs whose middle is left of the pointer', () => {
  expect(insertionIndex(['a', 'c'], measured, 10)).toBe(0);
  expect(insertionIndex(['a', 'c'], measured, 120)).toBe(1);
  expect(insertionIndex(['a', 'c'], measured, 290)).toBe(2);
});

test('commit writes the previewed index once; cancel writes nothing; step moves one place', () => {
  const onDrop = vi.fn();
  let order = ['a', 'b', 'c'];
  const adapter = createStripAdapter({ order: () => order, measured: () => measured, onDrop }, 1);
  const g = { source: { kind: 'external', id: 'a' }, pointer: { x: 160, y: 5 }, base: measured } as never;
  const key = adapter.targetKey(g);
  expect(key).toBe('1');
  const target = adapter.preview(g, key);
  expect([...target.rects.keys()]).toEqual(['b', 'a', 'c']);
  adapter.cancel();
  expect(onDrop).not.toHaveBeenCalled();
  adapter.commit(target, g);
  expect(onDrop).toHaveBeenCalledExactlyOnceWith('a', 1);
  onDrop.mockClear();
  expect(adapter.step!('a', { dir: 'left', resize: false })).toBeNull();
  const right = adapter.step!('a', { dir: 'right', resize: false });
  adapter.commit(right!, null);
  expect(onDrop).toHaveBeenCalledExactlyOnceWith('a', 1);
  expect(adapter.step!('a', { dir: 'up', resize: false })).toBeNull();
  order = ['a'];
  expect(adapter.step!('a', { dir: 'right', resize: false })).toBeNull();
});

test('a keyboard session previews each step from the last, Escape writes nothing, Enter writes once', () => {
  const onDrop = vi.fn();
  const order = ['a', 'b', 'c', 'd'];
  const wide = new Map<string, Rect>(order.map((id, i) => [id, rect(i * 101)]));
  const make = () => {
    onDrop.mockClear();
    return mountKeyboard(createStripAdapter({ order: () => order, measured: () => wide, onDrop }, 1), order);
  };
  let k = make();
  for (let i = 0; i < 3; i++) k.key('a', 'ArrowRight');
  k.key('a', 'Escape');
  expect(onDrop).not.toHaveBeenCalled();
  k = make();
  for (let i = 0; i < 3; i++) k.key('a', 'ArrowRight');
  k.key('a', 'Enter');
  expect(onDrop).toHaveBeenCalledExactlyOnceWith('a', 3);
});
