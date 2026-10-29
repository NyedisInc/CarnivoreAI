import { describe, expect, it } from 'vitest';
import { moveBefore, resolveMenuOrder } from './menu-order.svelte';

const rows = ['a', 'b', 'c', 'd'].map((id) => ({ id }));
const ids = (list: { id: string }[]): string[] => list.map((r) => r.id);

describe('menu order', () => {
  it('absent is the default order', () => {
    expect(ids(resolveMenuOrder(rows))).toEqual(['a', 'b', 'c', 'd']);
  });
  it('a stored order wins, a new row appends and a gone row drops out', () => {
    expect(ids(resolveMenuOrder(rows, ['c', 'gone', 'a']))).toEqual(['c', 'a', 'b', 'd']);
  });
  it('moveBefore lands above a row or last, and a no-op returns an equal list', () => {
    expect(moveBefore(['a', 'b', 'c'], 'a', 'c')).toEqual(['b', 'a', 'c']);
    expect(moveBefore(['a', 'b', 'c'], 'a', null)).toEqual(['b', 'c', 'a']);
    expect(moveBefore(['a', 'b', 'c'], 'b', 'b')).toEqual(['a', 'b', 'c']);
    expect(moveBefore(['a', 'b', 'c'], 'b', 'zzz')).toEqual(['a', 'b', 'c']);
  });
});
