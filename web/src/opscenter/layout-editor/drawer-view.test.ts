import { describe, expect, test } from 'vitest';
import { drawerList } from './drawer-groups';
import { arrange, buildView, isDrawerViewMode, isOpen, toggleFold } from './drawer-view';
import { WIDGET_TYPES, type WidgetType } from '../widgets/types';

const t = (key: string): string => key;
const rows = drawerList({ onSurface: [], disabled: () => false, query: '', t }).rows;
const none = (): string[] => [];
const names = (list: { row: { title: string } }[]): string[] => list.map((one) => one.row.title);
const sorted = (list: string[]): string[] => [...list].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));

describe('by name', () => {
  test('one flat list of every widget, sorted by name, no tree', () => {
    const view = buildView(rows, 'name', '', none);
    expect(view.sections).toEqual([]);
    expect(view.flat).toHaveLength(rows.length);
    expect(names(view.flat)).toEqual(sorted(names(view.flat)));
  });
});

describe('by type', () => {
  test('one fold per type sorted alphabetically by label, each sorted by name, every widget in exactly one', () => {
    const view = buildView(rows, 'type', '', none);
    expect(view.flat).toEqual([]);
    const order = view.sections.map((section) => section.type);
    expect(order).toEqual(sorted(order));
    expect(order).not.toEqual(WIDGET_TYPES.filter((type) => order.includes(type)));
    for (const section of view.sections) {
      expect(section.rows.every((one) => one.row.type === section.type)).toBe(true);
      expect(names(section.rows)).toEqual(sorted(names(section.rows)));
    }
    expect(view.sections.reduce((sum, section) => sum + section.rows.length, 0)).toBe(rows.length);
    expect(view.sections.every((section) => section.rows.length > 0)).toBe(true);
  });

  test('folds sort by the label the drawer shows, not the type id', () => {
    const label = (type: WidgetType): string => ({ kpi: 'zeta', list: 'Alpha', monitor: 'beta', feed: 'x', tool: 'y', pane: 'z', chart: 'w', plugin: 'v' })[type];
    const order = buildView(rows, 'type', '', none, label).sections.map((section) => label(section.type));
    expect(order).toEqual(sorted(order));
    expect(order[0]).toBe('Alpha');
  });

  test('numbers sort by value, so "2" comes before "10"', () => {
    const make = (title: string, widgetId: string) => ({ ...rows[0]!, title, widgetId });
    const list = arrange([make('Chart 10', 'a'), make('Chart 2', 'b')], '', none);
    expect(names(list)).toEqual(['Chart 2', 'Chart 10']);
  });

  test('the default view is the tree and only the two views are views', () => {
    expect(isDrawerViewMode('type')).toBe(true);
    expect(isDrawerViewMode('name')).toBe(true);
    expect(isDrawerViewMode('grid')).toBe(false);
  });
});

describe('search', () => {
  test('keeps only fuzzy matches, best first, with the matched letters', () => {
    const found = arrange(rows, 'nts', none);
    expect(found.length).toBeGreaterThan(0);
    for (const one of found) expect(one.indices.length).toBe(3);
    for (let at = 1; at < found.length; at += 1) expect(found[at - 1]!.score).toBeGreaterThanOrEqual(found[at]!.score);
    const unrelated = arrange(rows, 'qqqzzz', none);
    expect(unrelated).toEqual([]);
  });

  test('works in both views and ranks by score, not by name', () => {
    const flat = buildView(rows, 'name', 'note', none).flat;
    expect(flat[0]!.row.widgetId).toBe('core.notes');
    const tree = buildView(rows, 'type', 'note', none);
    expect(tree.sections.flatMap((section) => section.rows).map((one) => one.row.widgetId)).toContain('core.notes');
  });

  test('another word can match when the name does not, ranked under every name match, nothing highlighted', () => {
    const extra = (row: { widgetId: string }): string[] => (row.widgetId === 'core.notes' ? ['zebra'] : []);
    const found = arrange(rows, 'zebra', extra);
    expect(found.map((one) => one.row.widgetId)).toEqual(['core.notes']);
    expect(found[0]!.indices).toEqual([]);
    const mixed = arrange(rows, 'no', extra);
    const named = mixed.filter((one) => one.indices.length > 0);
    expect(mixed.slice(0, named.length)).toEqual(named);
  });
});

describe('folds', () => {
  const all: WidgetType[] = ['kpi', 'list', 'monitor'];

  test('a plain press toggles one type', () => {
    const folded = toggleFold(new Set(), 'kpi', all, false);
    expect([...folded]).toEqual(['kpi']);
    expect([...toggleFold(folded, 'kpi', all, false)]).toEqual([]);
  });

  test('Shift cascades: every type goes to the state the pressed one moves to', () => {
    const closed = toggleFold(new Set(), 'list', all, true);
    expect([...closed].sort()).toEqual([...all].sort());
    expect([...toggleFold(closed, 'list', all, true)]).toEqual([]);
  });

  test('a typed query draws every fold open and a folded one stays folded when it is cleared', () => {
    const folded = new Set<WidgetType>(['kpi']);
    expect(isOpen(folded, 'kpi', 'no')).toBe(true);
    expect(isOpen(folded, 'kpi', '  ')).toBe(false);
    expect(isOpen(folded, 'kpi', '')).toBe(false);
    expect([...folded]).toEqual(['kpi']);
  });
});
