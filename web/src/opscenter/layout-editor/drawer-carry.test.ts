import { describe, expect, test } from 'vitest';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { sidebarOffers, type SidebarHolds } from './drawer-carry';

const holds = (zone: string[]): SidebarHolds => ({ zone, glance: [], disabled: () => false, repeatable: () => false, t: (key) => key });

describe('sidebarOffers', () => {
  test('a held singleton moves, a held widget with views is added again', () => {
    expect(sidebarOffers(CORE_MANIFESTS['core.files']!, 'files', holds(['core.files'])).zone.moves).toBe('core.files');
    expect(sidebarOffers(CORE_MANIFESTS['core.tasks']!, 'tasks', holds(['core.tasks'])).zone.moves).toBeNull();
  });
});
