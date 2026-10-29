import { beforeEach, describe, expect, it } from 'vitest';
import { assignSeriesLooks, clearColorCache, mergeLegendSelection, seriesLook, toSrgb, type ColorContext } from './series-colors';

function fakeCtx(): ColorContext {
  let fill = '#000000';
  let px = [0, 0, 0, 0];
  let rgb = [0, 0, 0, 255];
  return {
    get fillStyle() { return fill; },
    set fillStyle(value) {
      const m = /^rgb\((\d+), (\d+), (\d+)\)$/.exec(String(value));
      if (m) { fill = String(value); rgb = [Number(m[1]), Number(m[2]), Number(m[3]), 255]; }
      else if (/^#[0-9a-f]{6}$/i.test(String(value))) fill = String(value);
    },
    clearRect() { px = [0, 0, 0, 0]; },
    fillRect() { px = rgb; },
    getImageData() { return { data: px }; },
  };
}

const palette = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];

describe('seriesLook', () => {
  it('gives every series of the first eight its own solid colour', () => {
    const looks = Array.from({ length: 8 }, (_, i) => seriesLook(i, palette));
    expect(new Set(looks.map((l) => l.color)).size).toBe(8);
    expect(looks.every((l) => !l.dashed)).toBe(true);
  });
  it('cycles and dashes from the ninth series', () => {
    expect(seriesLook(8, palette)).toEqual({ color: 'a', dashed: true });
    expect(seriesLook(10, palette)).toEqual({ color: 'c', dashed: true });
  });
});

describe('assignSeriesLooks', () => {
  it('keys a series once, in draw order', () => {
    const looks = assignSeriesLooks(['x', 'y', 'x', 'z'], palette);
    expect([...looks.keys()]).toEqual(['x', 'y', 'z']);
    expect(looks.get('z')?.color).toBe('c');
  });
});

describe('toSrgb', () => {
  beforeEach(clearColorCache);
  it('flattens a parsable colour to rgb()', () => {
    expect(toSrgb('rgb(10, 20, 30)', fakeCtx(), 'red')).toBe('rgb(10, 20, 30)');
  });
  it('falls back when the browser rejects the syntax', () => {
    expect(toSrgb('oklch(from nonsense)', fakeCtx(), '#fff')).toBe('#fff');
  });
});

describe('mergeLegendSelection', () => {
  it('keeps hidden series hidden, defaults new ones to shown and drops stale names', () => {
    expect(mergeLegendSelection({ a: false, gone: false, b: true }, ['a', 'b', 'c'])).toEqual({ a: false, b: true, c: true });
  });
});
