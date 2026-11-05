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
  it('keeps a four digit year, so a year typed digit by digit (0202 on the way to 2026) stays a valid input value', () => {
    expect(isoToLocal(localToIso('0202-10-30T09:05'))).toBe('0202-10-30T09:05');
  });
  it('answers nothing for a year past 9999, which no ISO reader takes', () => {
    expect(localToIso('20261-10-30T09:05')).toBe('');
  });
  it('answers nothing for an empty or unreadable value', () => {
    expect(localToIso('')).toBe('');
    expect(localToIso('nope')).toBe('');
    expect(isoToLocal('')).toBe('');
  });
});
