import { describe, expect, test, vi } from 'vitest';
import type { DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { declaredGroups } from './declared-nodes';

const action = (id: string, extra: Partial<DeclaredAction> = {}): DeclaredAction => ({ id, label: id, run: () => {}, ...extra });

describe('declaredGroups', () => {
  test('a radio set is a group of its own; plain actions between sets share one', () => {
    const groups = declaredGroups([
      action('sort:name', { checked: true }), action('sort:recent', { checked: false }),
      action('view-all'), action('refresh'),
      action('density:compact', { checked: true }), action('density:full', { checked: false }),
    ]);
    expect(groups.map((g) => g.map((n) => n.id))).toEqual([['sort:name', 'sort:recent'], ['view-all', 'refresh'], ['density:compact', 'density:full']]);
  });

  test('two radio sets side by side stay two groups (told apart by the id prefix)', () => {
    const groups = declaredGroups([action('group:status', { checked: true }), action('group:project', { checked: false }), action('density:compact', { checked: true })]);
    expect(groups.map((g) => g.length)).toEqual([2, 1]);
  });

  test('a tick is drawn as a checkbox and a blocked action carries its reason', () => {
    const [group] = declaredGroups([action('only-favorites', { checked: true, toggle: true }), action('clear', { blocked: 'nothing to clear' })]);
    expect(group![0]).toMatchObject({ checked: true, toggle: true });
    expect(group![1]).toMatchObject({ blocked: 'nothing to clear' });
  });

  test('a named group (the terminal) puts a hairline where the name changes', () => {
    const groups = declaredGroups([action('search', { group: 'shows' }), action('zoom', { group: 'shows' }), action('files', { group: 'drawers' })]);
    expect(groups.map((g) => g.map((n) => n.id))).toEqual([['search', 'zoom'], ['files']]);
  });

  test('a node runs the action', () => {
    const run = vi.fn();
    declaredGroups([action('x', { run })])[0]![0]!.run!();
    expect(run).toHaveBeenCalled();
  });
});
