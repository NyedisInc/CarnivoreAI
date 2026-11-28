import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { resolveZ, ZScaleError, zRungs } from './z-scale';

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8');
const rungs = zRungs(read('./tokens.css'));

const zOf = (path: string): string => /z-index:\s*([^;}]+)/.exec(read(path))?.[1] ?? 'missing';

describe('the stacking scale', () => {
  test('reads the rungs and resolves steps on them', () => {
    expect(rungs.size).toBeGreaterThan(20);
    expect(resolveZ('var(--oc-z-dialog)', rungs)).toBe(9999);
    expect(resolveZ('calc(var(--oc-z-page) + var(--oc-z-step))', rungs)).toBe(41);
    expect(resolveZ('calc(var(--oc-z-scrim) - var(--oc-z-step))', rungs)).toBe(1089);
    expect(resolveZ('var(--oc-z-modal)', rungs)).toBe(1100);
  });

  test('refuses what it cannot read instead of reading zero', () => {
    expect(() => resolveZ('var(--oc-z-nope)', rungs)).toThrow(ZScaleError);
    expect(() => resolveZ('auto', rungs)).toThrow(ZScaleError);
  });

  test('every rung after the step climbs above the one listed before it', () => {
    const order = [...rungs.keys()].filter((name) => name !== '--oc-z-step' && name !== '--oc-z-modal');
    const values = order.map((name) => resolveZ(`var(${name})`, rungs));
    for (let i = 1; i < values.length; i += 1) expect(values[i], order[i]).toBeGreaterThan(values[i - 1]);
  });

  test.each([
    '../plugins/taskmanager/TaskManagerTickConfirm.svelte',
  ])('%s is a dialog over every drawer', (path) => {
    const z = resolveZ(zOf(path), rungs);
    expect(z).toBe(resolveZ('var(--oc-z-dialog)', rungs));
    expect(z).toBeGreaterThan(resolveZ('var(--oc-z-drawer-float)', rungs));
    expect(z).toBeGreaterThan(resolveZ('var(--oc-z-sheet)', rungs));
  });
});
