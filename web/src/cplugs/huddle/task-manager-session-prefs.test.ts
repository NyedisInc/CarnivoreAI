import { describe, expect, test } from 'vitest';
import { effectiveNudge } from './task-manager-session-prefs';

describe('precedence (the server rule, mirrored)', () => {
  test.each([
    [undefined, true, true], [undefined, false, false], [true, false, true], [false, true, false], [true, true, true], [false, false, false],
  ])('own %s, project %s -> %s', (own, project, expected) => {
    expect(effectiveNudge(own, project)).toBe(expected);
  });
});
