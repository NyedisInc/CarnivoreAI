import { describe, expect, it } from 'vitest';
import { hitTerms, landingTop, markPieces } from './context-marks';

describe('hitTerms', () => {
  it('collects the distinct matched words, lowercase', () => {
    expect(hitTerms('a \u0002Zebra\u0003 b \u0002zebra\u0003 \u0002fish\u0003')).toEqual(['zebra', 'fish']);
  });
  it('is empty without marks', () => expect(hitTerms('plain')).toEqual([]));
});

describe('markPieces', () => {
  it('marks every occurrence, case-insensitive, and keeps the text whole', () => {
    const pieces = markPieces('zebrafish here and ZebraFish again', ['zebrafish']);
    expect(pieces.filter((p) => p.match)).toHaveLength(2);
    expect(pieces.map((p) => p.text).join('')).toBe('zebrafish here and ZebraFish again');
  });
  it('treats regex characters in a term as text', () => {
    expect(markPieces('a.b axb', ['a.b']).filter((p) => p.match).map((p) => p.text)).toEqual(['a.b']);
  });
  it('returns one plain piece without terms', () => expect(markPieces('x', [])).toEqual([{ text: 'x', match: false }]));
});

describe('landingTop', () => {
  it('centers a hit that fits', () => expect(landingTop(500, 1000, 100, null, 0)).toBe(800));
  it('never goes above the top', () => expect(landingTop(500, 10, 100, null, 0)).toBe(0));
  it('centers the first match of a tall hit, so the match is on screen', () => {
    const top = landingTop(500, 1000, 1500, 1900, 20);
    expect(1900).toBeGreaterThanOrEqual(top);
    expect(1920).toBeLessThanOrEqual(top + 500);
  });
  it('lands on the top of a tall hit with no match', () => expect(landingTop(500, 1000, 1500, null, 0)).toBe(1000));
});
