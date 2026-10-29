import { describe, expect, test } from 'vitest';

import { META } from '../engine/meta';
import { DECLARED_LIMITS, addInstance, copiesOf, insertAnalyticsRow, limitVerdict, resetLayout } from '../engine/model';
import { MAX_PER_SURFACE_CEILING, type WidgetManifest } from './types';
import { CORE_MANIFESTS } from './core-manifests';
import { FitDeclarationError, declarationOf } from './fit-declarations';
import { validateManifest } from './validate';

const ROW = { sizes: ['small'], anySize: true };
const CHART = 'analytics:11111111-1111-4111-8111-111111111111';
const CHART2 = 'analytics:22222222-2222-4222-8222-222222222222';

describe('every built-in declares a valid max_per_surface or none', () => {
  test.each(Object.values(CORE_MANIFESTS))('$id', (manifest) => {
    const limit = manifest.fits.max_per_surface;
    if (limit !== undefined) {
      expect(Number.isInteger(limit) && limit >= 1 && limit <= MAX_PER_SURFACE_CEILING).toBe(true);
    }
    if (manifest.instancing === 'singleton') expect(limit).toBe(1);
    expect(validateManifest(manifest as WidgetManifest).ok).toBe(true);
  });
});

describe('the declaration refuses a bad limit', () => {
  const rows = (fits: Record<string, unknown>, instancing = 'per-target') => [{ id: 'core.analytics', instancing, fits }];
  test.each([0, -1, 1.5, '2', true, MAX_PER_SURFACE_CEILING + 1])('%j is refused', (bad) => {
    expect(() => declarationOf('analytics', rows({ ...ROW, max_per_surface: bad }))).toThrow(FitDeclarationError);
  });
  test('a singleton may not declare more than 1', () => {
    expect(() => declarationOf('notes', [{ id: 'core.notes', instancing: 'singleton', fits: { ...ROW, max_per_surface: 2 } }])).toThrow(/singleton/);
  });
  test('absent is unlimited, a number is kept', () => {
    expect(declarationOf('analytics', rows(ROW)).max_per_surface).toBeUndefined();
    expect(declarationOf('analytics', rows({ ...ROW, max_per_surface: 3 })).max_per_surface).toBe(3);
  });
  test('the manifest validator refuses it too', () => {
    const bad = { ...CORE_MANIFESTS['core.analytics']!, fits: { ...CORE_MANIFESTS['core.analytics']!.fits, max_per_surface: 0 } };
    expect(validateManifest(bad as WidgetManifest).ok).toBe(false);
  });
});

describe('the model refuses a drop at the limit', () => {
  test('the built-in per-target widgets are unlimited today', () => {
    expect(DECLARED_LIMITS).toEqual({});
  });

  test('addInstance answers limit once the page holds that many, and the layout is untouched', () => {
    const limits = { analytics: 2 } as const;
    const one = addInstance(resetLayout(META), 'analytics', CHART.slice('analytics:'.length), '', META, limits);
    expect(one.refusal).toBeNull();
    const two = addInstance(one.layout, 'analytics', CHART2.slice('analytics:'.length), '', META, limits);
    expect(two.refusal).toBeNull();
    const three = addInstance(two.layout, 'analytics', '33333333-3333-4333-8333-333333333333', '', META, limits);
    expect(three.refusal).toBe('limit');
    expect(three.layout).toBe(two.layout);
  });

  test('a hidden copy counts, and so does the analytics insert', () => {
    const base = resetLayout(META);
    const hidden = { ...base, hidden: [...base.hidden, CHART as never] };
    expect(copiesOf(hidden, 'analytics')).toEqual([CHART]);
    expect(insertAnalyticsRow(hidden, [CHART2 as never], { analytics: 1 })).toBe(hidden);
    expect(insertAnalyticsRow(hidden, [CHART2 as never], { analytics: 2 })).not.toBe(hidden);
  });

  test('the live-terminal cap is a separate rule: a terminal limit never reads it', () => {
    let layout = resetLayout(META);
    for (let n = 0; n < 6; n += 1) layout = addInstance(layout, 'terminal', `s${n}`, '', META, {}).layout;
    expect(addInstance(layout, 'terminal', 's7', '', META, {}).refusal).toBe('cap');
  });
});

describe('the move offer at limit 1', () => {
  test('names the one copy a drop can move; none when empty or when the limit is higher', () => {
    const empty = resetLayout(META);
    expect(limitVerdict(empty, 'analytics', 1, { analytics: 1 })).toEqual({ refused: false, limit: 1, moves: null });
    const placed = addInstance(empty, 'analytics', CHART.slice('analytics:'.length), '', META, { analytics: 1 }).layout;
    expect(limitVerdict(placed, 'analytics', 1, { analytics: 1 })).toEqual({ refused: true, limit: 1, moves: CHART });
    expect(limitVerdict(placed, 'analytics', 1, { analytics: 2 }).moves).toBeNull();
  });
});
