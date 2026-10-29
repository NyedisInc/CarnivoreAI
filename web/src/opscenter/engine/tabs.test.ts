import { describe, expect, test } from 'vitest';
import {
  activeOf, addTab, closeTab, findTab, mergeGroup, migrate, moveTab, normalize, splitOut, tabsOf,
} from './tabs';

const P = 'terminal:@primary';
const A = 'terminal:ses_a';
const B = 'terminal:ses_b';
const C = 'terminal:ses_c';

describe('migration', () => {
  test('every instance slot becomes a one-tab group of itself; singletons hold no tabs', () => {
    expect(migrate([P, A, 'notes'])).toEqual({ [P]: { tabs: [P] }, [A]: { tabs: [A] } });
  });
  test('a slot with no stored group reads as its own single tab', () => {
    expect(tabsOf({}, A)).toEqual([A]);
    expect(activeOf({}, {}, A)).toBe(A);
  });
});

describe('uniqueness', () => {
  test('adding a session already in any group of the grid changes nothing', () => {
    const groups = migrate([P, A]);
    expect(addTab(groups, P, A)).toBe(groups);
    expect(findTab(groups, A)).toBe(A);
  });
  test('addTab appends, or inserts at an index', () => {
    const groups = addTab(addTab(migrate([P]), P, A), P, B, 1);
    expect(groups[P]?.tabs).toEqual([P, B, A]);
  });
  test('normalize keeps a tab found twice in its first group only', () => {
    const { groups } = normalize({ [P]: { tabs: [P, A] }, [A]: { tabs: [A, B] } }, [P, A]);
    expect(groups[P]?.tabs).toEqual([P, A]);
    expect(groups[A]?.tabs).toEqual([B]);
  });
});

describe('active tab', () => {
  test('a remembered tab that left the group falls back to the first', () => {
    const groups = { [P]: { tabs: [P, A] } };
    expect(activeOf(groups, { [P]: A }, P)).toBe(A);
    expect(activeOf(groups, { [P]: C }, P)).toBe(P);
  });
});

describe('close, move, split, merge', () => {
  test('closing the last tab names the emptied slot for removeCell', () => {
    expect(closeTab(migrate([A]), A)).toEqual({ groups: { [A]: { tabs: [] } }, emptied: A });
    expect(closeTab({ [P]: { tabs: [P, A] } }, A)).toEqual({ groups: { [P]: { tabs: [P] } }, emptied: null });
  });
  test('moveTab reorders inside one group', () => {
    const { groups, emptied } = moveTab({ [P]: { tabs: [P, A, B] } }, B, P, 0);
    expect(groups[P]?.tabs).toEqual([B, P, A]);
    expect(emptied).toBeNull();
  });
  test('moveTab across groups empties the source when it was the last tab', () => {
    const { groups, emptied } = moveTab(migrate([P, A]), A, P);
    expect(groups[P]?.tabs).toEqual([P, A]);
    expect(emptied).toBe(A);
  });
  test('splitOut gives a tab a group of its own at a new slot', () => {
    const { groups, emptied } = splitOut({ [P]: { tabs: [P, A] } }, A, C);
    expect(groups).toEqual({ [P]: { tabs: [P] }, [C]: { tabs: [A] } });
    expect(emptied).toBeNull();
  });
  test('mergeGroup appends every tab and leaves the source empty', () => {
    const groups = mergeGroup({ [P]: { tabs: [P] }, [A]: { tabs: [A, B] } }, A, P);
    expect(groups[P]?.tabs).toEqual([P, A, B]);
    expect(groups[A]?.tabs).toEqual([]);
  });
  test('normalize drops groups whose slot left the grid and names empty groups for removal', () => {
    const { groups, remove } = normalize({ [P]: { tabs: [P] }, [A]: { tabs: [] }, [B]: { tabs: [B] } }, [P, A]);
    expect(Object.keys(groups)).toEqual([P, A]);
    expect(remove).toEqual([A]);
  });
  test('operations never mutate their input', () => {
    const input = { [P]: { tabs: [P, A] } };
    const frozen = JSON.stringify(input);
    addTab(input, P, B);
    closeTab(input, A);
    moveTab(input, A, P, 0);
    splitOut(input, A, C);
    mergeGroup(input, P, C);
    expect(JSON.stringify(input)).toBe(frozen);
  });
});
