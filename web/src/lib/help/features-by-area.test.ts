import { describe, expect, it } from 'vitest';
import { findFeature, groupFeaturesByArea, type FeatureCatalogPayload } from './features-by-area';

function payload(overrides: Partial<FeatureCatalogPayload> = {}): FeatureCatalogPayload {
  return {
    available: true,
    areas: [
      { id: 'terminal', name: 'Terminal' },
      { id: 'home', name: 'Home screen' },
    ],
    catalog: [],
    changes: [],
    ...overrides,
  };
}

describe('groupFeaturesByArea', () => {
  it('orders areas exactly as areas.json lists them, not alphabetically', () => {
    const p = payload({
      catalog: [
        { id: 'a', name: 'A', summary: 's', area: 'home', status: 'stable' },
        { id: 'b', name: 'B', summary: 's', area: 'terminal', status: 'stable' },
      ],
    });
    const groups = groupFeaturesByArea(p);
    expect(groups.map((g) => g.id)).toEqual(['terminal', 'home']);
  });

  it('drops removed features and omits an area left with none', () => {
    const p = payload({
      catalog: [
        { id: 'a', name: 'A', summary: 's', area: 'home', status: 'removed' },
      ],
    });
    expect(groupFeaturesByArea(p)).toEqual([]);
  });

  it('keeps beta and deprecated features, carrying their status', () => {
    const p = payload({
      catalog: [
        { id: 'a', name: 'A', summary: 's', area: 'home', status: 'beta' },
        { id: 'b', name: 'B', summary: 's', area: 'home', status: 'deprecated' },
      ],
    });
    const groups = groupFeaturesByArea(p);
    expect(groups[0]?.features.map((f) => f.status)).toEqual(['beta', 'deprecated']);
  });

  it('sorts features within an area by name', () => {
    const p = payload({
      catalog: [
        { id: 'z', name: 'Zebra', summary: 's', area: 'home', status: 'stable' },
        { id: 'a', name: 'Apple', summary: 's', area: 'home', status: 'stable' },
      ],
    });
    const groups = groupFeaturesByArea(p);
    expect(groups[0]?.features.map((f) => f.id)).toEqual(['a', 'z']);
  });

  it('groups an area missing from areas.json under its own raw id, appended last', () => {
    const p = payload({
      catalog: [
        { id: 'a', name: 'A', summary: 's', area: 'terminal', status: 'stable' },
        { id: 'x', name: 'X', summary: 's', area: 'ghost-area', status: 'stable' },
      ],
    });
    const groups = groupFeaturesByArea(p);
    expect(groups.map((g) => g.id)).toEqual(['terminal', 'ghost-area']);
    expect(groups[1]?.name).toBe('ghost-area');
  });
});

describe('findFeature', () => {
  it('finds a feature by id across groups', () => {
    const groups = groupFeaturesByArea(
      payload({
        catalog: [{ id: 'x', name: 'X', summary: 's', area: 'home', status: 'stable' }],
      }),
    );
    expect(findFeature(groups, 'x')?.name).toBe('X');
    expect(findFeature(groups, 'missing')).toBeNull();
  });
});
