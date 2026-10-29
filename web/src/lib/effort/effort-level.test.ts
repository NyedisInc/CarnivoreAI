import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { EFFORT_LEVELS, effortClass, effortLevel } from './effort-level';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

interface LegacyEffort {
  LEVELS: string[];
  level: (e: unknown) => string | null;
  className: (e: unknown) => string;
}

function legacy(): LegacyEffort {
  const context: Record<string, unknown> = { console: { log() {} }, window: {} };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(repoRoot, 'client', 'js', 'effort-level.js'), 'utf8'), context);
  return (context['window'] as Record<string, unknown>)['EffortLevel'] as LegacyEffort;
}

describe('effortClass', () => {
  test('every recorded level maps to its own class', () => {
    expect(EFFORT_LEVELS.length).toBe(6);
    for (const level of EFFORT_LEVELS) {
      expect(effortClass(level)).toBe(`effort-level effort--${level}`);
    }
  });

  test('case and padding are normalised, as the harness spelling varies', () => {
    expect(effortLevel(' XHigh ')).toBe('xhigh');
  });

  test('unknown, absent and misspelled efforts paint nothing', () => {
    for (const value of [null, undefined, '', '  ', 'auto', 'x-high', 5, {}]) {
      expect(effortClass(value)).toBe('');
    }
  });
});

describe('the legacy twin', () => {
  test('loads, and carries the same levels in the same order', () => {
    const l = legacy();
    expect(Array.from(l.LEVELS)).toEqual([...EFFORT_LEVELS]);
  });

  test('answers the same class for every input', () => {
    const l = legacy();
    for (const value of [...EFFORT_LEVELS, ' MAX ', null, '', 'auto']) {
      expect(l.className(value)).toBe(effortClass(value));
    }
  });
});
