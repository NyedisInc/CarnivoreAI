import { describe, expect, it } from 'vitest';
import { isoToLocal, localToIso } from './when-iso';

describe('when-iso', () => {
  it('stamps the browser offset on a picked local time', () => {
    const iso = localToIso('2026-10-30T09:00');
    expect(iso).toMatch(/^2026-10-30T09:00:00[+-]\d\d:\d\d$/);
    expect(new Date(iso).getTime()).toBe(new Date('2026-10-30T09:00').getTime());
  });
  it('round trips to the input value', () => {
    expect(isoToLocal(localToIso('2026-10-30T09:05'))).toBe('2026-10-30T09:05');
  });
  it('answers nothing for an empty or unreadable value', () => {
    expect(localToIso('')).toBe('');
    expect(localToIso('nope')).toBe('');
    expect(isoToLocal('')).toBe('');
  });
});
