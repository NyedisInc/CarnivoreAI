import { describe, expect, test } from 'vitest';
import { drawerGroups, drawerList, groupRows, listKinds, type GroupInputs } from './drawer-groups';
import { refusePlacement, placementRefusal, dismissRefusal } from '../widgets/chrome/refusal-toast.svelte';
import { t as translate } from '../../lib/i18n/index.svelte';
import type { SlotId } from '../engine/types';

const t: GroupInputs['t'] = (key, params) => translate(key, params);

function inputs(over: Partial<GroupInputs> = {}): GroupInputs {
  return {
    onSurface: ['terminal:@primary', 'notes'] as SlotId[],
    disabled: () => false,
    query: '',
    t,
    ...over,
  };
}

const ids = (list: ReturnType<typeof drawerGroups>): string[] => list.groups.flatMap((group) => group.rows.map((row) => row.widgetId));

describe('drawerGroups', () => {
  test('groups follow the category order, never empty, and the pane kinds stay picker entries', () => {
    const list = drawerGroups(inputs());
    expect(list.groups.map((group) => group.category)).toEqual(['overview', 'sessions', 'catalog', 'monitoring', 'tools']);
    expect(ids(list)).not.toContain('core.terminal');
    expect(ids(list)).not.toContain('core.browser');
  });

  test('every row carries its type label and a family is always addable with its copy count', () => {
    const rows = groupRows(inputs({ onSurface: ['analytics:a', 'analytics:b', 'notes'] as SlotId[] }));
    const analytics = rows.find((row) => row.widgetId === 'core.analytics')!;
    expect(analytics).toMatchObject({ family: true, state: 'addable', placed: 2, type: 'chart', cell: null });
    expect(rows.find((row) => row.widgetId === 'core.notes')).toMatchObject({ state: 'placed', placed: 1, type: 'tool' });
  });

  test('a widget of another page is addable here: no row is refused for its place', () => {
    const shown = drawerGroups(inputs());
    const rows = shown.groups.flatMap((group) => group.rows);
    expect(rows.find((row) => row.widgetId === 'core.projects')).toMatchObject({ state: 'addable', refusal: null, reason: '' });
    expect(rows.every((row) => row.state !== 'refused')).toBe(true);
  });

  test('a switched-off widget is the one refusal, with its sentence', () => {
    const rows = groupRows(inputs({ disabled: (id) => id === 'core.files' }));
    expect(rows.find((row) => row.widgetId === 'core.files')).toMatchObject({
      state: 'refused',
      refusal: 'disabled',
      sentence: 'files is switched off on the widgets page',
    });
  });

  test('search matches the type label and a family preset word', () => {
    expect(ids(drawerGroups(inputs({ query: 'monitor' })))).toEqual(
      expect.arrayContaining(['core.scheduled-tasks', 'core.keep-awake']),
    );
    const extra = drawerGroups(inputs({ query: 'spend', extraWords: { 'core.analytics': ['spend map'] } }));
    expect(ids(extra)).toEqual(['core.analytics']);
  });
});

describe('refusePlacement', () => {
  test('shows one line, replaces it with a newer one, and clears on dismiss', () => {
    refusePlacement('first');
    refusePlacement('second');
    expect(placementRefusal.line).toBe('second');
    dismissRefusal();
    expect(placementRefusal.line).toBe('');
  });
});

describe('the compact list', () => {
  test('drawerList is one flat list of the same rows, addable before placed before switched off', () => {
    const list = drawerList(inputs({ disabled: (id) => id === 'core.files' }));
    expect(list.rows.map((row) => row.widgetId).sort()).toEqual(ids(drawerGroups(inputs())).sort());
    expect(list.rows.at(-1)?.widgetId).toBe('core.files');
    const rank = { addable: 0, placed: 1, refused: 2 } as const;
    const ranks = list.rows.map((row) => rank[row.state]);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });

  test('a kind keeps only that kind, with search on top; the kind filter lists every kind the list has', () => {
    const tools = drawerList(inputs({ kind: 'tool' }));
    expect(tools.rows.length).toBeGreaterThan(0);
    expect(tools.rows.every((row) => row.type === 'tool')).toBe(true);
    expect(drawerList(inputs({ kind: 'tool', query: 'files' })).rows.map((row) => row.widgetId)).toEqual(['core.files']);
    expect(drawerList(inputs({ kind: 'kpi', query: 'files' })).rows).toEqual([]);
    const kinds = listKinds(inputs());
    expect(kinds).toContain('tool');
    expect(drawerList(inputs()).rows.every((row) => kinds.includes(row.type))).toBe(true);
  });
});
