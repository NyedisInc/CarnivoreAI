import { describe, expect, it } from 'vitest';
import { WARROOM_STATE } from './state';

describe('war room peek width state', () => {
  const field = WARROOM_STATE.peekwidth;
  it('defaults to 1150, kept per device, and the old zoom field is gone', () => {
    expect(field.default).toBe(1150);
    expect(field.home).toBe('device');
    expect('peekzoom' in WARROOM_STATE).toBe(false);
  });
  it('accepts an integer 0 to 2300 only', () => {
    for (const ok of [0, 1, 1150, 2300]) expect(field.valid(ok)).toBe(true);
    for (const bad of [-1, 2301, 2.5, '1150', null, undefined, NaN]) expect(field.valid(bad)).toBe(false);
  });
});
