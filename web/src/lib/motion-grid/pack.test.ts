import { describe, expect, it } from 'vitest';
import { firstFit, flow, hit, pack, type PackItem } from './pack';

const mk = (id: string, x: number, y: number, w: number, h: number): PackItem => ({ id, x, y, w, h });

function clean(items: readonly PackItem[]): boolean {
  return items.every((a, i) => items.every((b, j) => i === j || !hit(a, b)));
}

describe('pack', () => {
  it('pulls items up with no hole and keeps the input order', () => {
    const out = pack([mk('a', 0, 5, 4, 2), mk('b', 4, 9, 4, 2), mk('c', 0, 20, 4, 1)], 12);
    expect(out).toEqual([mk('a', 0, 0, 4, 2), mk('b', 4, 0, 4, 2), mk('c', 0, 2, 4, 1)]);
  });

  it('drops an overlapping item below the one it hits, by y then x order', () => {
    const out = pack([mk('a', 0, 0, 6, 3), mk('b', 3, 0, 6, 2)], 12);
    expect(out).toEqual([mk('a', 0, 0, 6, 3), mk('b', 3, 3, 6, 2)]);
  });

  it('caps a too-wide item to the columns and clamps x', () => {
    const out = pack([mk('a', 5, 0, 30, 1)], 24);
    expect(out).toEqual([mk('a', 0, 0, 24, 1)]);
  });

  it('holds the pinned item at its cell and pushes the rest below it', () => {
    const out = pack([mk('a', 0, 0, 6, 2), mk('b', 6, 0, 6, 2), mk('c', 0, 2, 6, 2)], 12, { id: 'c', x: 0, y: 0 });
    expect(out.find((o) => o.id === 'c')).toEqual(mk('c', 0, 0, 6, 2));
    expect(out.find((o) => o.id === 'a')).toEqual(mk('a', 0, 2, 6, 2));
    expect(out.find((o) => o.id === 'b')).toEqual(mk('b', 6, 0, 6, 2));
    expect(clean(out)).toBe(true);
  });

  it('pulls a pinned item up while the cells above are free', () => {
    const out = pack([mk('a', 0, 0, 4, 1), mk('p', 8, 7, 4, 2)], 12, { id: 'p', x: 8, y: 7 });
    expect(out.find((o) => o.id === 'p')).toEqual(mk('p', 8, 0, 4, 2));
  });

  it('ignores a pin whose id is absent', () => {
    expect(pack([mk('a', 0, 3, 2, 2)], 12, { id: 'zz', x: 0, y: 0 })).toEqual([mk('a', 0, 0, 2, 2)]);
  });

  it('never overlaps on a crowded pseudo-random set', () => {
    const items: PackItem[] = [];
    let s = 7;
    for (let n = 0; n < 40; n += 1) {
      s = (s * 1103515245 + 12345) % 2147483648;
      items.push(mk(`i${n}`, s % 24, (s >> 5) % 30, 1 + ((s >> 9) % 8), 1 + ((s >> 13) % 5)));
    }
    const out = pack(items, 24, { id: 'i3', x: 2, y: 4 });
    expect(clean(out)).toBe(true);
    expect(out.map((o) => o.id)).toEqual(items.map((o) => o.id));
  });
});

describe('flow', () => {
  it('first-fits in y then x order for a narrower grid', () => {
    const out = flow([mk('a', 0, 0, 4, 2), mk('b', 4, 0, 4, 2), mk('c', 8, 0, 4, 1)], 6);
    expect(out).toEqual([mk('a', 0, 0, 4, 2), mk('b', 0, 2, 4, 2), mk('c', 0, 4, 4, 1)]);
  });

  it('caps widths to the column count', () => {
    expect(flow([mk('a', 0, 0, 9, 1)], 1)).toEqual([mk('a', 0, 0, 1, 1)]);
  });
});

describe('firstFit', () => {
  it('returns the first free cell, rows first', () => {
    expect(firstFit([], 24, 4, 3)).toEqual({ x: 0, y: 0 });
    expect(firstFit([mk('a', 0, 0, 22, 2)], 24, 4, 3)).toEqual({ x: 0, y: 2 });
    expect(firstFit([mk('a', 0, 0, 12, 2)], 24, 4, 3)).toEqual({ x: 12, y: 0 });
  });
});
