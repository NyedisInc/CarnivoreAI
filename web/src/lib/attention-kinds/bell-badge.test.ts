import { describe, expect, test } from 'vitest';
import { badgeOf } from './bell-badge';

const row = (severity: 'error' | 'warn' | 'info') => ({ severity });

describe('the badge', () => {
  test('counts every shown row but an info alert, painted by the highest severity, nothing at zero', () => {
    expect(badgeOf([row('warn'), row('error'), row('info')])).toEqual({ count: 2, severity: 'error' });
    expect(badgeOf([row('warn')])).toEqual({ count: 1, severity: 'warn' });
    expect(badgeOf([row('info')])).toEqual({ count: 0, severity: null });
    expect(badgeOf([])).toEqual({ count: 0, severity: null });
  });
});
