import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { countErrors, judge } from '../scripts/type-check-ratchet/ratchet.mjs';

const FINISHED = '9 COMPLETED 4883 FILES 2 ERRORS 58 WARNINGS 3 FILES_WITH_PROBLEMS';

describe('type-check ratchet', () => {
  it('counts error rows only, and notes a finished run', () => {
    const out = ['1 ERROR "src/a.ts" 1:1 "x"', '2 WARNING "src/b.ts" 2:2 "y"', '3 ERROR "src/c.ts" 3:3 "z"', FINISHED].join('\n');
    expect(countErrors(out)).toEqual({ errors: 2, completed: true });
    expect(countErrors('1 ERROR "src/a.ts" 1:1 "x"').completed).toBe(false);
  });

  it('refuses a count above the baseline, tells the owner to lower it below, and passes an equal one', () => {
    expect(judge({ errors: 25, completed: true }, 24).code).toBe(1);
    expect(judge({ errors: 24, completed: true }, 24).code).toBe(0);
    const under = judge({ errors: 20, completed: true }, 24);
    expect(under.code).toBe(0);
    expect(under.message).toContain('lower');
  });

  it('treats a run that did not finish as could-not-determine, never a pass', () => {
    expect(judge({ errors: 0, completed: false }, 24).code).toBe(2);
  });

  it('keeps a baseline whose per-lane notes add up to the number', () => {
    const baseline = JSON.parse(readFileSync(new URL('../scripts/type-check-ratchet/baseline.json', import.meta.url), 'utf8'));
    const lanes = Object.values(baseline.remaining as Record<string, number>).reduce((sum, n) => sum + n, 0);
    expect(lanes).toBe(baseline.errors);
  });
});
