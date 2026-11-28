import { describe, expect, test } from 'vitest';

import type { Arrangement } from './arrangement-model';
import { META } from './meta';
import { resetLayout } from './model';
import { retireArrangement, retireBoards, retireGroups, retireTab } from './retired-stores';

/** Retired cell id to the Mark II cell that takes its slot. */
const SUCCESSOR: Record<string, string> = {
  'task-manager': 'task-manager-mk2',
  'task-list': 'task-manager-mk2',
  'task-manager-all': 'task-manager-mk2-all',
};

describe('the pure swaps', () => {
  test('a widget tab of each retired widget becomes its successor; other tabs keep their exact key', () => {
    for (const [retired, successor] of Object.entries(SUCCESSOR)) expect(retireTab(`widget:core.${retired}`)).toBe(`widget:core.${successor}`);
    expect(retireTab('widget:core.tasks')).toBe('widget:core.tasks');
    expect(retireTab('terminal:row:7')).toBe('terminal:row:7');
  });

  test('a value with nothing retired comes back as the same object', () => {
    const boards = [{ id: 'home', name: 'home', layout: resetLayout(META, 'home') }];
    expect(retireBoards(boards)).toBe(boards);
    const map: Arrangement = { v: 1, sessions: { a: { layout: null, groups: { 'terminal:@primary': { tabs: ['terminal:@primary'] } } } } };
    expect(retireArrangement(map).map).toBe(map);
  });
});

describe('tab groups', () => {
  test('a group holding a retired tab and its successor keeps one copy, in the first place either stood', () => {
    const groups = { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-manager', 'widget:core.task-manager-mk2'] } };
    expect(retireGroups(groups)['terminal:@primary']!.tabs).toEqual(['terminal:@primary', 'widget:core.task-manager-mk2']);
  });
});
