import { describe, expect, test } from 'vitest';
import { CORE_MANIFESTS } from './core-manifests';
import { validateManifest } from './validate';
import { cellManifestFor, drawingIds, hasViews, isScopeSwitch, isViewCell, mergedIds, mergePlacement, viewOfPlacement, viewWidgetId, viewsOf } from './views';

const PAIRS: readonly (readonly [string, string])[] = [
  ['core.tasks', 'core.tasks-all'],
  ['core.bookmarks', 'core.bookmarks-all'],
  ['core.automations', 'core.automations-all'],
  ['core.task-manager', 'core.task-manager-all'],
  ['core.task-manager-mk2', 'core.task-manager-mk2-all'],
];

describe('the merged pairs', () => {
  test.each(PAIRS)('%s offers the selected session and %s as its all sessions view', (local, all) => {
    const manifest = CORE_MANIFESTS[local]!;
    expect(viewsOf(manifest).map((view) => [view.id, view.widget])).toEqual([['session', local], ['all', all]]);
    expect(viewsOf(manifest).map((view) => view.titleKey)).toEqual(['widget.view.session', 'widget.view.all']);
    expect(hasViews(manifest)).toBe(true);
    expect(isViewCell(manifest)).toBe(false);
    expect(isViewCell(CORE_MANIFESTS[all])).toBe(true);
    expect(CORE_MANIFESTS[all]!.viewOf).toBe(local);
  });

  test('every manifest with views passes the validator, view cells included', () => {
    for (const manifest of Object.values(CORE_MANIFESTS)) expect(validateManifest(manifest).ok, manifest.id).toBe(true);
  });

  test('a widget with one face has no views, and the global-only pipeline is not a pair', () => {
    for (const id of ['core.notes', 'core.files', 'core.changes', 'core.crosstalk', 'core.pipeline']) {
      expect(viewsOf(CORE_MANIFESTS[id])).toEqual([]);
      expect(hasViews(CORE_MANIFESTS[id])).toBe(false);
    }
  });

  test('only the pairs carry a view cell, so nothing else is hidden from the catalog', () => {
    const cells = Object.values(CORE_MANIFESTS).filter((manifest) => isViewCell(manifest)).map((manifest) => manifest.id);
    expect(cells.sort()).toEqual(PAIRS.map(([, all]) => all).sort());
  });
});

describe('a placement\'s view', () => {
  const tasks = CORE_MANIFESTS['core.tasks']!;

  test('absent or stale falls back to the first view; a stored one wins', () => {
    expect(viewOfPlacement(tasks, undefined)?.id).toBe('session');
    expect(viewOfPlacement(tasks, 'gone')?.id).toBe('session');
    expect(viewOfPlacement(tasks, 'all')?.id).toBe('all');
    expect(viewOfPlacement(CORE_MANIFESTS['core.notes'], 'all')).toBeNull();
  });

  test('the drawing manifest and the icon id follow the view', () => {
    expect(cellManifestFor(tasks, 'all', CORE_MANIFESTS).id).toBe('core.tasks-all');
    expect(cellManifestFor(tasks, null, CORE_MANIFESTS).id).toBe('core.tasks');
    expect(cellManifestFor(CORE_MANIFESTS['core.notes']!, 'all', CORE_MANIFESTS).id).toBe('core.notes');
    expect(viewWidgetId(CORE_MANIFESTS['core.task-manager']!, 'all')).toBe('core.task-manager-all');
    expect(viewWidgetId(CORE_MANIFESTS['core.task-manager']!, null)).toBe('core.task-manager');
    expect(viewWidgetId(CORE_MANIFESTS['core.task-manager-mk2']!, 'all')).toBe('core.task-manager-mk2-all');
    expect(viewWidgetId(CORE_MANIFESTS['core.task-manager-mk2']!, null)).toBe('core.task-manager-mk2');
  });

  test('the all sessions cell accepts no session scope and the selected session cell does', () => {
    expect(cellManifestFor(tasks, 'all', CORE_MANIFESTS).scope).toBeUndefined();
    expect(cellManifestFor(tasks, 'session', CORE_MANIFESTS).scope).toBe('session');
  });

  test('a grid slot of either cell counts as the widget being placed', () => {
    expect(drawingIds(tasks)).toEqual(['core.tasks', 'core.tasks-all']);
    expect(drawingIds(CORE_MANIFESTS['core.notes']!)).toEqual(['core.notes']);
  });
});

describe('migration of stored placements', () => {
  const merged = mergedIds(CORE_MANIFESTS);

  test.each(PAIRS)('%s old id maps to the merged widget with the all view', (local, all) => {
    expect(mergePlacement({ widget: all }, merged)).toEqual({ widget: local, view: 'all' });
  });

  test('the local ids and every other id stay as they were', () => {
    expect(mergePlacement({ widget: 'core.tasks' }, merged)).toEqual({ widget: 'core.tasks' });
    expect(mergePlacement({ widget: 'core.pipeline' }, merged)).toEqual({ widget: 'core.pipeline' });
  });
});

describe('isScopeSwitch: the selected session | all sessions pair (item 1048)', () => {
  test('is true for a session widget with an all sibling and false for one face or other looks', () => {
    expect(isScopeSwitch(CORE_MANIFESTS['core.tasks'])).toBe(true);
    expect(isScopeSwitch(CORE_MANIFESTS['core.notes'])).toBe(false);
    expect(isScopeSwitch({ views: [{ id: 'all', titleKey: 'x', widget: 'a' }, { id: 'session', titleKey: 'y', widget: 'b' }] })).toBe(false);
    expect(isScopeSwitch(undefined)).toBe(false);
  });
});
