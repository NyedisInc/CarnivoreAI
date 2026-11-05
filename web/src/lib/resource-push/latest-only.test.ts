import { describe, expect, it } from 'vitest';
import { latestOnly } from './latest-only';

describe('latestOnly', () => {
  it('lets only the newest request publish', () => {
    const gate = latestOnly();
    const first = gate.begin();
    const second = gate.begin();
    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it('overtakes every request in flight on invalidate', () => {
    const gate = latestOnly();
    const current = gate.begin();
    gate.invalidate();
    expect(current()).toBe(false);
    expect(gate.begin()()).toBe(true);
  });
});
