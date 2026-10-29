import { describe, expect, it } from 'vitest';
import { boxOverride } from './box-override';

describe('the harness box override', () => {
  it('reads whole-pixel w and h from the query', () => {
    expect(boxOverride(new URLSearchParams('w=420&h=300'))).toEqual({ w: 420, h: 300 });
    expect(boxOverride(new URLSearchParams('w=420'))).toEqual({ w: 420 });
  });

  it('is null for a query with neither, and drops junk or out-of-range values', () => {
    expect(boxOverride(new URLSearchParams('widget=core.notes'))).toBeNull();
    expect(boxOverride(new URLSearchParams('w=abc&h=-4'))).toBeNull();
    expect(boxOverride(new URLSearchParams('w=0&h=9999'))).toBeNull();
    expect(boxOverride(new URLSearchParams('w=12px&h=300'))).toEqual({ h: 300 });
  });
});
