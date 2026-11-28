import { describe, expect, it } from 'vitest';
import * as sections from './task-manager-status-sections';
import * as prefs from './task-manager-session-prefs';

describe('huddle leftovers stay deleted', () => {
  it('has no SECTION_COLOR export', () => {
    expect('SECTION_COLOR' in sections).toBe(false);
  });
  it('has no setSessionNudge export', () => {
    expect('setSessionNudge' in prefs).toBe(false);
  });
});
