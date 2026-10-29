
import { describe, expect, it } from 'vitest';
import { parseServerTime } from './format';

describe('parseServerTime', () => {
  it('reads a marker-less naive stamp as UTC, not local', () => {
    expect(parseServerTime('2026-09-18T20:00:38.406050')).toBe(Date.parse('2026-09-18T20:00:38.406Z'));
  });

  it('reads a marker-less second-precision stamp as UTC', () => {
    expect(parseServerTime('2026-09-18T20:00:38')).toBe(Date.parse('2026-09-18T20:00:38Z'));
  });

  it('passes a Z-suffixed stamp through unchanged', () => {
    expect(parseServerTime('2026-09-18T20:00:38Z')).toBe(Date.parse('2026-09-18T20:00:38Z'));
  });

  it('passes a +00:00 offset stamp through unchanged', () => {
    expect(parseServerTime('2026-09-18T20:00:38+00:00')).toBe(Date.parse('2026-09-18T20:00:38Z'));
  });

  it('passes a -04:00 offset stamp through unchanged, and it lands on the same instant as the Z stamp above', () => {
    const at = parseServerTime('2026-09-18T16:00:38-04:00');
    expect(at).toBe(Date.parse('2026-09-18T20:00:38Z'));
    expect(at).toBe(parseServerTime('2026-09-18T20:00:38Z'));
  });

  it('a naive stamp and its Z-suffixed twin disagree by exactly the viewer offset, proving the bug this closes', () => {
    const naive = parseServerTime('2026-09-18T20:00:38.406050');
    const marked = parseServerTime('2026-09-18T20:00:38.406050Z');
    expect(naive).toBe(marked);
  });

  it('answers NaN for null', () => {
    expect(Number.isNaN(parseServerTime(null))).toBe(true);
  });

  it('answers NaN for undefined', () => {
    expect(Number.isNaN(parseServerTime(undefined))).toBe(true);
  });

  it('answers NaN for an empty or whitespace-only string', () => {
    expect(Number.isNaN(parseServerTime(''))).toBe(true);
    expect(Number.isNaN(parseServerTime('   '))).toBe(true);
  });

  it('answers NaN for unparseable garbage', () => {
    expect(Number.isNaN(parseServerTime('not-a-date'))).toBe(true);
  });
});
